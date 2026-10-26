import asyncio
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
    Delivered,
    MessageDelta,
    MessageEnd,
    MessageStart,
    RunEnd,
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
    ) -> None:
        self._provider = provider
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

    def request_compaction(self) -> None:
        self._compact_requested = True

    def restore(self, summary: str) -> None:
        self._conversation = [SummaryTurn(text=summary)]
        self._context_tokens = 0

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
        self._gate.begin_run()
        self._compaction_failed = False
        self._verify_compaction = False
        recovering = False
        recent: deque[str] = deque(maxlen=self._limits.repeat_limit)
        try:
            for _ in range(self._limits.max_turns):
                if self._should_compact():
                    try:
                        yield await self._compact(prompt, cancel)
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
                            case ToolCallReady(call=call):
                                turn.calls.append(call)
                            case NativeReady(content=content):
                                turn.native = content
                            case UsageReport(usage=delta):
                                self._usage = self._usage + delta
                                self._context_tokens = delta.prompt_tokens
                                self._check_compaction_helped()
                            case Stop(reason=reason):
                                turn.stop = reason
                except ContextOverflow as error:
                    yield MessageEnd(turn.message_id, "", "")
                    if recovering:
                        yield RunEnd(RunEndReason.ERROR, self._usage, str(error))
                        return
                    recovering = True
                    try:
                        yield await self._compact(prompt, cancel)
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
                        for event in self._skip(call, _UNFINISHED[turn.stop]):
                            yield event
                    if turn.stop == "refusal":
                        yield RunEnd(RunEndReason.ERROR, self._usage, "model declined the request")
                        return
                    continue
                for call in assistant.tool_calls:
                    recent.append(_signature(call))
                    if len(recent) == recent.maxlen and len(set(recent)) == 1:
                        yield RunEnd(
                            RunEndReason.LIMIT, self._usage, "repeated identical tool call"
                        )
                        return
                    async for event in self._execute(call, provenance, cancel):
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

    async def _compact(self, prompt: UserTurn, cancel: asyncio.Event) -> Compacted:
        self._compact_requested = False
        request = LlmRequest(
            system=self._context.system(),
            messages=(*to_llm(self._conversation), LlmMessage(role="user", content=SUMMARY_PROMPT)),
            tools=self._tools.schemas(),
        )
        text: list[str] = []
        called = False
        try:
            async for event in self._events(request, cancel):
                match event:
                    case TextDelta(text=chunk):
                        text.append(chunk)
                    case ToolCallReady():
                        called = True
                    case UsageReport(usage=delta):
                        self._usage = self._usage + delta
                    case _:
                        pass
        except ProviderError as error:
            raise CompactionFailed(str(error)) from error
        summary = extract_summary("".join(text))
        if cancel.is_set() or called or not summary:
            raise CompactionFailed("the model did not produce a summary")
        before = self._context_tokens
        self._conversation = [SummaryTurn(text=summary), prompt]
        self._context_tokens = 0
        self._verify_compaction = True
        return Compacted(summary, before)

    async def _events(self, request: LlmRequest, cancel: asyncio.Event) -> AsyncIterator[LlmEvent]:
        stream = self._provider.stream(request, cancel=cancel).__aiter__()
        limit = self._limits.first_token_timeout_s
        try:
            while True:
                try:
                    event = await interruptible(anext(stream), cancel, limit)
                except StopAsyncIteration:
                    return
                except Interrupted:
                    return
                except TimedOut:
                    raise ProviderError(f"model produced no output for {limit:g}s") from None
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
                    self._invoke(prepared, cancel, replace(self._tool_ctx, emit=queue.put_nowait))
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
        yield self._finish(call, result)

    async def _invoke(
        self, prepared: PreparedCall, cancel: asyncio.Event, ctx: ToolCtx
    ) -> ToolResult:
        try:
            return await interruptible(prepared.execute(ctx), cancel, self._limits.tool_timeout_s)
        except TimedOut:
            return ToolResult("Tool timed out", is_error=True)
        except (ToolError, SandboxError, OSError, UnicodeDecodeError) as error:
            return ToolResult(f"{type(error).__name__}: {error}", is_error=True)

    def _skip(self, call: ToolCallRequest, reason: str) -> tuple[AgentEvent, ...]:
        view = ToolCallView(id=call.id, name=call.name, risk=ToolRisk.EXEC, args=call.args)
        return ToolStart(view), self._finish(call, ToolResult(reason, is_error=True))

    def _finish(self, call: ToolCallRequest, result: ToolResult) -> ToolEnd:
        self._conversation.append(
            ToolResultTurn(
                call_id=call.id, name=call.name, content=result.content, is_error=result.is_error
            )
        )
        return ToolEnd(call.id, result)

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


def _signature(call: ToolCallRequest) -> str:
    return f"{call.name}:{json.dumps(call.args, sort_keys=True)}"
