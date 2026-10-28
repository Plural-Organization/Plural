import asyncio
import itertools
import json
from collections import deque
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from dataclasses import dataclass, field, replace

import structlog
from pydantic import ValidationError

from plural.agent.compaction import SUMMARY_PROMPT, extract_summary
from plural.agent.context import ContextBuilder
from plural.agent.events import (
    AgentEvent,
    Compacted,
    Compacting,
    ContextFill,
    Delivered,
    MessageDelta,
    MessageEnd,
    MessageStart,
    RunEnd,
    Spend,
    ToolEnd,
    ToolOutput,
    ToolStart,
)
from plural.agent.gate import PolicyGate
from plural.agent.interrupt import Interrupted, TimedOut, interruptible
from plural.agent.messages import (
    AssistantTurn,
    Message,
    SummaryTurn,
    ToolResultTurn,
    UserTurn,
    to_llm,
)
from plural.agent.providers.base import (
    ContextOverflow,
    LlmEvent,
    LlmMessage,
    LLMProvider,
    LlmRequest,
    NativeContent,
    NativeReady,
    ProviderActivity,
    ProviderBusy,
    ProviderError,
    Stop,
    StopReason,
    TextDelta,
    ThinkingDelta,
    ToolCallReady,
    ToolCallRequest,
    UsageReport,
)
from plural.agent.sandbox.base import SandboxError
from plural.agent.tools.base import PreparedCall, ToolCtx, ToolError, ToolResult
from plural.agent.tools.registry import ToolRegistry, UnknownTool
from plural.core.ports import IdGenerator
from plural.core.provenance import merge
from plural.protocol.models import Provenance, RunEndReason, ToolCallView, ToolRisk, Usage

log = structlog.get_logger(__name__)


class CompactionFailed(Exception):
    pass


@dataclass(frozen=True, slots=True)
class LoopLimits:
    max_turns: int = 50
    repeat_limit: int = 3
    tool_timeout_s: float = 600.0
    first_token_timeout_s: float = 120.0
    idle_timeout_s: float = 60.0
    context_window: int = 128_000
    compact_at: float = 0.75
    retries: int = 3
    retry_delay_s: float = 2.0


@dataclass(slots=True)
class _Turn:
    message_id: str
    text: list[str] = field(default_factory=list[str])
    thinking: list[str] = field(default_factory=list[str])
    calls: list[ToolCallRequest] = field(default_factory=list[ToolCallRequest])
    native: NativeContent | None = None
    stop: StopReason = "end_turn"

    def assistant(self) -> AssistantTurn:
        return AssistantTurn(
            text="".join(self.text), tool_calls=tuple(self.calls), native=self.native
        )


class AgentLoop:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        tools: ToolRegistry,
        gate: PolicyGate,
        context: ContextBuilder,
        tool_ctx: ToolCtx,
        ids: IdGenerator,
        limits: LoopLimits | None = None,
        helper: LLMProvider | None = None,
    ) -> None:
        self._provider = provider
        self._helper = helper
        self._spending: dict[tuple[str, str], Spend] = {}
        self._tools = tools
        self._gate = gate
        self._context = context
        self._tool_ctx = tool_ctx
        self._ids = ids
        self._limits = limits or LoopLimits()
        self._conversation: list[Message] = []
        self._steer: deque[UserTurn] = deque()
        self._follow_up: deque[UserTurn] = deque()
        self._usage = Usage()
        self._context_tokens = 0
        self._compact_requested = False
        self._compaction_failed = False
        self._verify_compaction = False
        self._provider_close_tasks: set[asyncio.Task[None]] = set()

    def spend(self, role: str, who: str, usage: Usage, *, uses: int = 0) -> None:
        key = (role, who)
        previous = self._spending.get(key, Spend(role, who, Usage(), 0))
        self._spending[key] = Spend(role, who, previous.usage + usage, previous.uses + uses)

    def take_spending(self) -> tuple[Spend, ...]:
        spending = tuple(
            spend
            for spend in self._spending.values()
            if spend.uses or spend.usage.prompt_tokens or spend.usage.output_tokens
        )
        self._spending = {}
        return spending

    @property
    def provider(self) -> LLMProvider:
        return self._provider

    @property
    def helper(self) -> LLMProvider | None:
        return self._helper

    @property
    def limits(self) -> LoopLimits:
        return self._limits

    @property
    def usage(self) -> Usage:
        return self._usage

    @property
    def conversation(self) -> Sequence[Message]:
        return tuple(self._conversation)

    def steer(self, turn: UserTurn) -> None:
        self._steer.append(turn)

    def follow_up(self, turn: UserTurn) -> None:
        self._follow_up.append(turn)

    def swap_provider(
        self,
        provider: LLMProvider,
        *,
        context_window: int | None = None,
        helper: LLMProvider | None = None,
    ) -> None:
        retired = [self._provider, self._helper]
        self._provider = provider
        self._helper = helper
        for previous in retired:
            close = getattr(previous, "close", None)
            if close is not None and previous not in (provider, helper):
                task = asyncio.create_task(close())
                self._provider_close_tasks.add(task)
                task.add_done_callback(self._provider_close_tasks.discard)
        if context_window is not None:
            self._limits = replace(self._limits, context_window=context_window)
        self._conversation = [
            message.model_copy(update={"native": None})
            if isinstance(message, AssistantTurn) and message.native is not None
            else message
            for message in self._conversation
        ]
        self._context_tokens = 0
        self._compaction_failed = False

    async def close(self) -> None:
        close = getattr(self._provider, "close", None)
        if close is not None:
            await close()
        if self._provider_close_tasks:
            await asyncio.gather(*self._provider_close_tasks, return_exceptions=True)

    def request_compaction(self) -> None:
        self._compact_requested = True

    def fill(self) -> ContextFill:
        return ContextFill(
            self._context_tokens, self._limits.context_window, self._limits.compact_at
        )

    @property
    def can_compact(self) -> bool:
        return len(self._conversation) >= 2

    async def compact(self, *, cancel: asyncio.Event) -> AsyncIterator[AgentEvent]:
        """Summarize the conversation now, outside a prompt, so everyone sees it happen."""
        self._usage = Usage()
        yield Compacting(self._context_tokens)
        try:
            yield await self._compact(None, cancel)
        except CompactionFailed as error:
            yield RunEnd(RunEndReason.ERROR, self._usage, f"compaction failed: {error}")
            return
        yield self.fill()
        yield RunEnd(RunEndReason.ABORTED if cancel.is_set() else RunEndReason.STOP, self._usage)

    def restore(self, conversation: Sequence[Message]) -> None:
        self._conversation = list(conversation)
        self._context_tokens = sum(_estimate_tokens(message) for message in conversation)

    def cancel_pending(self, prompt_id: str) -> bool:
        for queue in (self._steer, self._follow_up):
            for turn in queue:
                if turn.id == prompt_id:
                    queue.remove(turn)
                    return True
        return False

    def drain_pending(self) -> list[UserTurn]:
        pending = [*self._steer, *self._follow_up]
        self._steer.clear()
        self._follow_up.clear()
        return pending

    async def run(self, prompt: UserTurn, *, cancel: asyncio.Event) -> AsyncIterator[AgentEvent]:
        provenance = prompt.provenance
        self._conversation.append(prompt)
        self._usage = Usage()
        self.spend("main", "", Usage(), uses=1)
        self._gate.begin_run()
        self._compaction_failed = False
        self._verify_compaction = False
        recovering = False
        recent: deque[str] = deque(maxlen=self._limits.repeat_limit)
        try:
            for _ in range(self._limits.max_turns):
                if self._should_compact():
                    yield Compacting(self._context_tokens)
                    try:
                        yield await self._compact(prompt, cancel)
                        yield self.fill()
                    except CompactionFailed as error:
                        self._compaction_failed = True
                        log.warning("agent.compaction_failed", error=str(error))
                    if cancel.is_set():
                        yield RunEnd(RunEndReason.ABORTED, self._usage)
                        return
                turn = _Turn(self._ids.new("m_"))
                yield MessageStart(turn.message_id)
                try:
                    async for event in self._events(self._request(), cancel):
                        match event:
                            case TextDelta(text=text):
                                turn.text.append(text)
                                yield MessageDelta(turn.message_id, text, thinking=False)
                            case ThinkingDelta(text=text):
                                turn.thinking.append(text)
                                yield MessageDelta(turn.message_id, text, thinking=True)
                            case ProviderActivity():
                                pass
                            case ToolCallReady(call=call):
                                turn.calls.append(call)
                            case NativeReady(content=content):
                                turn.native = content
                            case UsageReport(usage=delta):
                                self._usage = self._usage + delta
                                self.spend("main", "", delta)
                                self._context_tokens = delta.prompt_tokens
                                self._check_compaction_helped()
                                yield self.fill()
                            case Stop(reason=reason):
                                turn.stop = reason
                except ContextOverflow as error:
                    yield MessageEnd(turn.message_id, "", "")
                    if recovering:
                        yield RunEnd(RunEndReason.ERROR, self._usage, str(error))
                        return
                    recovering = True
                    yield Compacting(self._context_tokens)
                    try:
                        yield await self._compact(prompt, cancel)
                        yield self.fill()
                    except CompactionFailed as failure:
                        yield RunEnd(RunEndReason.ERROR, self._usage, f"context is full: {failure}")
                        return
                    continue
                except ProviderError as error:
                    yield MessageEnd(turn.message_id, "".join(turn.text), "".join(turn.thinking))
                    yield RunEnd(RunEndReason.ERROR, self._usage, str(error))
                    return
                recovering = False
                assistant = turn.assistant()
                if assistant.text or assistant.tool_calls or not cancel.is_set():
                    self._conversation.append(assistant)
                yield MessageEnd(turn.message_id, assistant.text, "".join(turn.thinking))
                if cancel.is_set():
                    yield RunEnd(RunEndReason.ABORTED, self._usage)
                    return
                if turn.stop in _UNFINISHED:
                    for call in assistant.tool_calls:
                        start, end = self._skip(call, _UNFINISHED[turn.stop])
                        self._answer(call, end.result)
                        yield start
                        yield end
                    if turn.stop == "refusal":
                        yield RunEnd(RunEndReason.ERROR, self._usage, "model declined the request")
                        return
                    continue
                for group in self._groups(assistant.tool_calls):
                    for call in group:
                        recent.append(_signature(call))
                        if len(recent) == recent.maxlen and len(set(recent)) == 1:
                            yield RunEnd(
                                RunEndReason.LIMIT, self._usage, "repeated identical tool call"
                            )
                            return
                    async for event in self._execute_group(group, provenance, cancel):
                        yield event
                    if cancel.is_set():
                        yield RunEnd(RunEndReason.ABORTED, self._usage)
                        return
                queued = self._next_input(has_tool_calls=bool(assistant.tool_calls))
                if not assistant.tool_calls and not queued:
                    yield RunEnd(RunEndReason.STOP, self._usage)
                    return
                if queued:
                    yield Delivered(tuple(message.id for message in queued))
                for message in queued:
                    provenance = merge(provenance, message.provenance)
                    self._conversation.append(message)
            yield RunEnd(RunEndReason.LIMIT, self._usage, "max turns reached")
        finally:
            self._settle()

    def _threshold(self) -> float:
        return self._limits.context_window * self._limits.compact_at

    def _should_compact(self) -> bool:
        if len(self._conversation) < 2:
            return False
        if self._compact_requested:
            return True
        return not self._compaction_failed and self._context_tokens >= self._threshold()

    def _check_compaction_helped(self) -> None:
        if not self._verify_compaction:
            return
        self._verify_compaction = False
        if self._context_tokens >= self._threshold():
            self._compaction_failed = True
            log.warning(
                "agent.compaction_ineffective",
                prompt_tokens=self._context_tokens,
                window=self._limits.context_window,
            )

    async def _compact(self, prompt: UserTurn | None, cancel: asyncio.Event) -> Compacted:
        self._compact_requested = False
        request = LlmRequest(
            system=self._context.system(),
            messages=(*to_llm(self._conversation), LlmMessage(role="user", content=SUMMARY_PROMPT)),
            tools=self._tools.schemas(),
        )
        summary = ""
        for provider in (self._helper, self._provider):
            if provider is None:
                continue
            try:
                summary = await self._summarize(request, provider, cancel)
                self.spend(
                    "fast" if provider is self._helper else "main", "compact", Usage(), uses=1
                )
                break
            except CompactionFailed as error:
                if cancel.is_set() or provider is self._provider:
                    raise
                log.warning("agent.helper_compaction_failed", error=str(error))
        before = self._context_tokens
        self._conversation = [SummaryTurn(text=summary), *([prompt] if prompt is not None else [])]
        self._context_tokens = sum(_estimate_tokens(message) for message in self._conversation)
        self._verify_compaction = True
        return Compacted(summary, before)

    async def _summarize(
        self, request: LlmRequest, provider: LLMProvider, cancel: asyncio.Event
    ) -> str:
        text: list[str] = []
        called = False
        role = "fast" if provider is self._helper else "main"
        try:
            async for event in self._events(request, cancel, provider):
                match event:
                    case TextDelta(text=chunk):
                        text.append(chunk)
                    case ToolCallReady():
                        called = True
                    case UsageReport(usage=delta):
                        self._usage = self._usage + delta
                        self.spend(role, "compact", delta)
                    case _:
                        pass
        except ProviderError as error:
            raise CompactionFailed(str(error)) from error
        summary = extract_summary("".join(text))
        if cancel.is_set() or called or not summary:
            raise CompactionFailed("the model did not produce a summary")
        return summary

    async def _events(
        self, request: LlmRequest, cancel: asyncio.Event, provider: LLMProvider | None = None
    ) -> AsyncIterator[LlmEvent]:
        for attempt in itertools.count():
            started = False
            try:
                async for event in self._attempt(request, cancel, provider or self._provider):
                    started = True
                    yield event
                return
            except ProviderBusy as error:
                if started or attempt >= self._limits.retries:
                    raise
                delay = self._limits.retry_delay_s * 2**attempt
                log.warning(
                    "agent.provider_busy", error=str(error), attempt=attempt + 1, delay=delay
                )
                try:
                    await interruptible(asyncio.sleep(delay), cancel)
                except Interrupted:
                    return

    async def _attempt(
        self, request: LlmRequest, cancel: asyncio.Event, provider: LLMProvider
    ) -> AsyncIterator[LlmEvent]:
        stream = provider.stream(request, cancel=cancel).__aiter__()
        limit = self._limits.first_token_timeout_s
        event_count = 0
        last_event_kind: str | None = None
        try:
            while True:
                try:
                    event = await interruptible(anext(stream), cancel, limit)
                except StopAsyncIteration:
                    return
                except Interrupted:
                    return
                except TimedOut:
                    log.warning(
                        "agent.provider_timeout",
                        provider=type(provider).__name__,
                        timeout_s=limit,
                        events_received=event_count,
                        last_event_kind=last_event_kind,
                    )
                    raise ProviderError(f"model produced no output for {limit:g}s") from None
                event_count += 1
                last_event_kind = event.kind
                if isinstance(event, ProviderActivity):
                    last_event_kind = event.source
                    continue
                limit = self._limits.idle_timeout_s
                yield event
        finally:
            if isinstance(stream, AsyncGenerator):
                await stream.aclose()

    def _next_input(self, *, has_tool_calls: bool) -> list[UserTurn]:
        if self._steer:
            steered = list(self._steer)
            self._steer.clear()
            return steered
        if not has_tool_calls and self._follow_up:
            return [self._follow_up.popleft()]
        return []

    def _request(self) -> LlmRequest:
        return LlmRequest(
            system=self._context.system(),
            messages=to_llm(self._conversation),
            tools=self._tools.schemas(),
        )

    def _groups(self, calls: Sequence[ToolCallRequest]) -> list[list[ToolCallRequest]]:
        groups: list[list[ToolCallRequest]] = []
        for call in calls:
            if groups and self._reads_only(call) and self._reads_only(groups[-1][0]):
                groups[-1].append(call)
            else:
                groups.append([call])
        return groups

    def _reads_only(self, call: ToolCallRequest) -> bool:
        if call.parse_error is not None:
            return False
        try:
            return self._tools.prepare(call).risk is ToolRisk.READ
        except (UnknownTool, ValidationError):
            return False

    async def _execute_group(
        self, group: Sequence[ToolCallRequest], provenance: Provenance, cancel: asyncio.Event
    ) -> AsyncIterator[AgentEvent]:
        if len(group) == 1:
            async for event in self._execute(group[0], provenance, cancel):
                if isinstance(event, ToolEnd):
                    self._answer(group[0], event.result)
                yield event
            return
        ended: dict[str, ToolEnd] = {}
        queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()

        async def pump(call: ToolCallRequest) -> None:
            try:
                async for event in self._execute(call, provenance, cancel):
                    queue.put_nowait(event)
            finally:
                queue.put_nowait(None)

        tasks = [asyncio.create_task(pump(call)) for call in group]
        try:
            running = len(tasks)
            while running:
                event = await queue.get()
                if event is None:
                    running -= 1
                    continue
                if isinstance(event, ToolEnd):
                    ended[event.call_id] = event
                yield event
        finally:
            for task in tasks:
                task.cancel()
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        for outcome in outcomes:
            if isinstance(outcome, Exception):
                raise outcome
        for call in group:
            if (end := ended.get(call.id)) is not None:
                self._answer(call, end.result)

    async def _execute(
        self, call: ToolCallRequest, provenance: Provenance, cancel: asyncio.Event
    ) -> AsyncIterator[AgentEvent]:
        if call.parse_error is not None:
            for event in self._skip(call, f"Invalid tool call: {call.parse_error}"):
                yield event
            return
        try:
            prepared = self._tools.prepare(call)
        except (UnknownTool, ValidationError) as error:
            for event in self._skip(call, f"Invalid tool call: {error}"):
                yield event
            return
        view = ToolCallView(
            id=call.id,
            name=prepared.name,
            risk=prepared.risk,
            subject=prepared.subject,
            args=call.args,
        )
        yield ToolStart(view)
        try:
            verdict = await interruptible(
                self._gate.check(view, subject=prepared.subject, provenance=provenance), cancel
            )
            if verdict.allowed:
                queue: asyncio.Queue[str] = asyncio.Queue()
                runner = asyncio.create_task(
                    self._invoke(
                        prepared,
                        cancel,
                        replace(
                            self._tool_ctx,
                            emit=queue.put_nowait,
                            provenance=provenance,
                            cancel=cancel,
                        ),
                    )
                )
                try:
                    while not runner.done() or not queue.empty():
                        getter = asyncio.create_task(queue.get())
                        await asyncio.wait({runner, getter}, return_when=asyncio.FIRST_COMPLETED)
                        if getter.done():
                            yield ToolOutput(call.id, getter.result())
                        else:
                            getter.cancel()
                    result = runner.result()
                finally:
                    if not runner.done():
                        runner.cancel()
            else:
                result = ToolResult(f"Denied: {verdict.reason}", is_error=True)
        except Interrupted:
            result = ToolResult(_ABORTED, is_error=True)
        yield ToolEnd(call.id, result)

    async def _invoke(
        self, prepared: PreparedCall, cancel: asyncio.Event, ctx: ToolCtx
    ) -> ToolResult:
        try:
            return await interruptible(prepared.execute(ctx), cancel, self._limits.tool_timeout_s)
        except TimedOut:
            return ToolResult("Tool timed out", is_error=True)
        except (ToolError, SandboxError, OSError, UnicodeDecodeError) as error:
            return ToolResult(f"{type(error).__name__}: {error}", is_error=True)

    def _skip(self, call: ToolCallRequest, reason: str) -> tuple[ToolStart, ToolEnd]:
        view = ToolCallView(id=call.id, name=call.name, risk=ToolRisk.EXEC, args=call.args)
        return ToolStart(view), ToolEnd(call.id, ToolResult(reason, is_error=True))

    def _answer(self, call: ToolCallRequest, result: ToolResult) -> None:
        self._conversation.append(
            ToolResultTurn(
                call_id=call.id, name=call.name, content=result.content, is_error=result.is_error
            )
        )

    def _settle(self) -> None:
        for index in range(len(self._conversation) - 1, -1, -1):
            message = self._conversation[index]
            if isinstance(message, AssistantTurn):
                answered = {
                    m.call_id
                    for m in self._conversation[index + 1 :]
                    if isinstance(m, ToolResultTurn)
                }
                for call in message.tool_calls:
                    if call.id not in answered:
                        self._conversation.append(
                            ToolResultTurn(
                                call_id=call.id,
                                name=call.name,
                                content="Not executed: run interrupted",
                                is_error=True,
                            )
                        )
                return


_ABORTED = "Not executed: run aborted"

_UNFINISHED: dict[StopReason, str] = {
    "max_tokens": "Not executed: the response hit the output limit before the call was complete",
    "refusal": "Not executed: the model declined the request",
}


def _estimate_tokens(message: Message) -> int:
    match message:
        case ToolResultTurn(content=text) | UserTurn(text=text) | SummaryTurn(text=text):
            return len(text) // 4
        case AssistantTurn(text=text, tool_calls=calls):
            return (len(text) + sum(len(_signature(call)) for call in calls)) // 4


def _signature(call: ToolCallRequest) -> str:
    return f"{call.name}:{json.dumps(call.args, sort_keys=True)}"
