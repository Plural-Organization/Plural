import asyncio
import json
import time
from collections import deque
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field, replace

import structlog
from pydantic import ValidationError

from plural.agent.briefing import BRIEFING_TAG
from plural.agent.compaction import SUMMARY_SYSTEM, extract_tagged, summary_request, with_files
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
    ToolsLoaded,
    ToolStart,
)
from plural.agent.gate import PolicyGate
from plural.agent.interrupt import Interrupted, TimedOut, interruptible
from plural.agent.messages import (
    PLUGIN_SOURCE,
    AssistantTurn,
    Message,
    NotesTurn,
    SummaryTurn,
    ToolResultTurn,
    UserTurn,
    kept_from,
    settled,
    to_llm,
)
from plural.agent.prompts import prompt
from plural.agent.providers.base import (
    ContextOverflow,
    LlmEvent,
    LlmMessage,
    LLMProvider,
    LlmRequest,
    NativeContent,
    NativeReady,
    ProviderActivity,
    ProviderError,
    Stop,
    StopReason,
    TextDelta,
    ThinkingDelta,
    ToolCallReady,
    ToolCallRequest,
    ToolSchema,
    UsageReport,
)
from plural.agent.providers.resilient import ResilientProvider
from plural.agent.sandbox.base import SandboxError
from plural.agent.telemetry import RequestDump, observed
from plural.agent.tools.base import PreparedCall, ToolCtx, ToolError, ToolResult
from plural.agent.tools.registry import ToolRegistry, UnknownTool
from plural.core.ports import IdGenerator
from plural.core.provenance import merge
from plural.protocol.models import (
    Origin,
    Provenance,
    Role,
    RunEndReason,
    ToolCallView,
    ToolRisk,
    Usage,
)

log = structlog.get_logger(__name__)


class CompactionFailed(Exception):
    pass


class BriefingFailed(Exception):
    pass


class AskFailed(Exception):
    pass


ASIDE = f"\n\n{prompt('aside')}"


SHARED = Provenance(initiator_id="shared-context", initiator_role=Role.VIEWER, origin=Origin.DIRECT)


@dataclass(frozen=True, slots=True)
class LoopLimits:
    max_turns: int = 50
    repeat_limit: int = 3
    tool_timeout_s: float = 600.0
    first_token_timeout_s: float = 120.0
    idle_timeout_s: float = 60.0
    # None until the provider says how much its model takes; set it to hold a window fixed.
    context_window: int | None = None
    # Room left for the reply: the conversation is summarized once it leaves less than this.
    compact_reserve: int = 16_384
    # The newest part of the conversation a compaction keeps as it is, in estimated tokens.
    keep_recent: int = 20_000
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


# The window assumed for a provider that does not say what its model takes.
FALLBACK_WINDOW = 128_000


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
        dump: RequestDump | None = None,
    ) -> None:
        self._dump = dump
        self._spending: dict[tuple[str, str], Spend] = {}
        self._tools = tools
        self._gate = gate
        self._context = context
        self._tool_ctx = tool_ctx
        self._ids = ids
        self._limits = limits or LoopLimits()
        self._provider = self._resilient(provider)
        self._helper = self._resilient(helper) if helper is not None else None
        self._prompt: tuple[str, tuple[ToolSchema, ...]] | None = None
        self._conversation: list[Message] = []
        self._notes: list[NotesTurn] = []
        self._shared = False
        self._steer: deque[UserTurn] = deque()
        self._follow_up: deque[UserTurn] = deque()
        self._usage = Usage()
        # The prompt size the provider last reported, and how many messages that prompt held.
        self._context_tokens = 0
        self._measured = 0
        self._window = self._limits.context_window
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
        return self._provider.inner

    @property
    def helper(self) -> LLMProvider | None:
        return self._helper.inner if self._helper is not None else None

    @property
    def dump(self) -> RequestDump | None:
        return self._dump

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
        retired = [wrapper.inner for wrapper in (self._provider, self._helper) if wrapper]
        self._provider = self._resilient(provider)
        self._helper = self._resilient(helper) if helper is not None else None
        for previous in retired:
            close = getattr(previous, "close", None)
            if close is not None and previous not in (provider, helper):
                task = asyncio.create_task(close())
                self._provider_close_tasks.add(task)
                task.add_done_callback(self._provider_close_tasks.discard)
        self._limits = replace(self._limits, context_window=context_window)
        self._window = context_window
        self._conversation = [
            message.model_copy(update={"native": None})
            if isinstance(message, AssistantTurn) and message.native is not None
            else message
            for message in self._conversation
        ]
        self._context_tokens = 0
        self._measured = 0
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
        window = self._window or FALLBACK_WINDOW
        return ContextFill(self._tokens(), window, self._threshold_of(window) / window)

    @property
    def can_compact(self) -> bool:
        return len(self._conversation) >= 2

    async def compact(self, *, cancel: asyncio.Event) -> AsyncIterator[AgentEvent]:
        """Summarize the conversation now, outside a prompt, so everyone sees it happen."""
        self._usage = Usage()
        yield Compacting(self._tokens())
        try:
            yield await self._compact(None, cancel, "manual")
        except CompactionFailed as error:
            yield RunEnd(RunEndReason.ERROR, self._usage, f"compaction failed: {error}")
            return
        yield self.fill()
        yield RunEnd(RunEndReason.ABORTED if cancel.is_set() else RunEndReason.STOP, self._usage)

    def mark_shared(self) -> None:
        self._shared = True

    def add_notes(self, turn: NotesTurn) -> None:
        self._notes.append(turn)
        self._shared = True

    def add_context(self, turn: NotesTurn) -> bool:
        """Notes from the host's own plugins: unlike a briefing, they do not mark the run shared.

        A note that repeats the plugin's latest one in the conversation is left out, so a hook
        that says the same each run does not pile up copies. False when it was left out.
        """
        latest = next(
            (
                message
                for message in reversed([*self._conversation, *self._notes])
                if isinstance(message, NotesTurn) and message.source == turn.source
            ),
            None,
        )
        if latest is not None and latest.text == turn.text:
            return False
        self._notes.append(turn)
        return True

    def load_tools(self, names: Sequence[str]) -> None:
        """Declare deferred tools loaded in an earlier session, before the next run."""
        self._tools.load(names)

    def restore(self, conversation: Sequence[Message]) -> None:
        self._conversation = list(conversation)
        self._shared = any(
            isinstance(message, NotesTurn) and not message.source.startswith(PLUGIN_SOURCE)
            for message in conversation
        )
        self._context_tokens = 0
        self._measured = 0

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
        provenance = merge(prompt.provenance, SHARED) if self._shared else prompt.provenance
        self._conversation.extend(self._notes)
        self._notes.clear()
        self._conversation.append(prompt)
        self._usage = Usage()
        self.spend("main", "", Usage(), uses=1)
        self._gate.begin_run()
        self._prompt = (self._context.system(), self._tools.schemas())
        revision = self._tools.revision
        self._compaction_failed = False
        self._verify_compaction = False
        recovering = False
        recent: deque[str] = deque(maxlen=self._limits.repeat_limit)
        try:
            for _ in range(self._limits.max_turns):
                if self._should_compact():
                    reason = "requested" if self._compact_requested else "threshold"
                    yield Compacting(self._tokens())
                    try:
                        yield await self._compact(prompt, cancel, reason)
                        yield self.fill()
                    except CompactionFailed as error:
                        self._compaction_failed = True
                        log.warning("agent.compaction_failed", error=str(error))
                    if cancel.is_set():
                        yield RunEnd(RunEndReason.ABORTED, self._usage)
                        return
                turn = _Turn(self._ids.new("m_"))
                yield MessageStart(turn.message_id)
                measured = len(self._conversation)
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
                                if delta.prompt_tokens:
                                    self._context_tokens = delta.prompt_tokens
                                    self._measured = measured
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
                    yield Compacting(self._tokens())
                    try:
                        yield await self._compact(prompt, cancel, "overflow")
                        yield self.fill()
                    except CompactionFailed as failure:
                        yield RunEnd(RunEndReason.ERROR, self._usage, f"context is full: {failure}")
                        return
                    continue
                except ProviderError as error:
                    yield MessageEnd(turn.message_id, "".join(turn.text), "".join(turn.thinking))
                    reason = str(error)
                    if "image" in reason.lower() and self._drop_images():
                        reason = f"{reason} (the images were removed so the session can go on)"
                    yield RunEnd(RunEndReason.ERROR, self._usage, reason)
                    return
                recovering = False
                await self._learn_window()
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
                    if limit := self._gate.turn_limit(usage=self._usage, provenance=provenance):
                        yield RunEnd(RunEndReason.LIMIT, self._usage, limit)
                        return
                    continue
                ended: list[ToolResult] = []
                for group in self._groups(assistant.tool_calls):
                    for call in group:
                        recent.append(_signature(call))
                        if len(recent) == recent.maxlen and len(set(recent)) == 1:
                            yield RunEnd(
                                RunEndReason.LIMIT, self._usage, "repeated identical tool call"
                            )
                            return
                    async for event in self._execute_group(group, provenance, cancel):
                        if isinstance(event, ToolEnd):
                            ended.append(event.result)
                        yield event
                    if cancel.is_set():
                        yield RunEnd(RunEndReason.ABORTED, self._usage)
                        return
                if self._tools.revision != revision:
                    # Tools loaded this turn are declared from the next model call on.
                    revision = self._tools.revision
                    known = {schema.name for schema in self._prompt[1]}
                    schemas = self._tools.schemas()
                    self._prompt = (self._prompt[0], schemas)
                    if fresh := tuple(s.name for s in schemas if s.name not in known):
                        yield ToolsLoaded(fresh)
                # Tools that all ask to terminate hand the turn back without another model call.
                has_tool_calls = bool(ended) and not all(result.terminate for result in ended)
                if (has_tool_calls or self._steer or self._follow_up) and (
                    limit := self._gate.turn_limit(usage=self._usage, provenance=provenance)
                ):
                    yield RunEnd(RunEndReason.LIMIT, self._usage, limit)
                    return
                queued = self._next_input(has_tool_calls=has_tool_calls)
                if not has_tool_calls and not queued:
                    yield RunEnd(RunEndReason.STOP, self._usage)
                    return
                if queued:
                    yield Delivered(tuple(message.id for message in queued))
                for message in queued:
                    provenance = merge(provenance, message.provenance)
                    self._conversation.append(message)
            yield RunEnd(RunEndReason.LIMIT, self._usage, "max turns reached")
        finally:
            self._prompt = None
            self._settle()

    def _threshold_of(self, window: int) -> int:
        # A window smaller than twice the reserve still gets half of itself for the conversation.
        return max(window - self._limits.compact_reserve, window // 2)

    def _threshold(self) -> int | None:
        """The size at which the conversation is summarized; None before the window is known."""
        return self._threshold_of(self._window) if self._window is not None else None

    def _tokens(self) -> int:
        """The provider's last count of the prompt, plus an estimate of what came after it."""
        added = self._conversation[self._measured :]
        return self._context_tokens + sum(_estimate_tokens(message) for message in added)

    async def _learn_window(self) -> None:
        if self._limits.context_window is not None:
            return
        ask = getattr(self._provider.inner, "context_window", None)
        learned = await ask() if ask is not None else None
        if learned:
            self._window = learned
        elif self._window is None:
            self._window = FALLBACK_WINDOW

    def _should_compact(self) -> bool:
        if len(self._conversation) < 2:
            return False
        if self._compact_requested:
            return True
        # Until the first call says how big the window is, only an overflow compacts.
        threshold = self._threshold()
        return not self._compaction_failed and threshold is not None and self._tokens() >= threshold

    def _check_compaction_helped(self) -> None:
        if not self._verify_compaction:
            return
        self._verify_compaction = False
        threshold = self._threshold()
        if threshold is not None and self._context_tokens >= threshold:
            self._compaction_failed = True
            log.warning(
                "agent.compaction_ineffective",
                prompt_tokens=self._context_tokens,
                window=self._window,
            )

    async def _compact(
        self, prompt: UserTurn | None, cancel: asyncio.Event, reason: str
    ) -> Compacted:
        """Summarize the older part of the conversation and keep the newest part as it is."""
        self._compact_requested = False
        first = self._conversation[0] if self._conversation else None
        previous = first.text if isinstance(first, SummaryTurn) else None
        start = 1 if previous is not None else 0
        end = self._cut(start) or len(self._conversation)
        history = self._conversation[start:end]
        request = LlmRequest(
            system=SUMMARY_SYSTEM,
            messages=(LlmMessage(role="user", content=summary_request(history, previous)),),
        )
        summary = ""
        role = "main"
        for provider in (self._helper, self._provider):
            if provider is None:
                continue
            try:
                summary = await self._summarize(request, provider, cancel)
                role = "fast" if provider is self._helper else "main"
                self.spend(role, "compact", Usage(), uses=1)
                break
            except CompactionFailed as error:
                if cancel.is_set() or provider is self._provider:
                    raise
                log.warning("agent.helper_compaction_failed", error=str(error))
        summary = with_files(summary, history, previous)
        # Thinking blocks are bound to the history they were written after, which the summary
        # replaces; the kept turns go on with their text and tool calls only.
        tail = [
            message.model_copy(update={"native": None})
            if isinstance(message, AssistantTurn)
            else message
            for message in self._conversation[end:]
        ]
        kept_prompt = prompt is not None and any(
            isinstance(message, UserTurn) and message.id == prompt.id for message in tail
        )
        before = self._tokens()
        self._conversation = [
            SummaryTurn(text=summary),
            *([prompt] if prompt is not None and not kept_prompt else []),
            *tail,
        ]
        self._context_tokens = 0
        self._measured = 0
        self._verify_compaction = True
        log.info(
            "context.compacted",
            reason=reason,
            role=role,
            tokens_before=before,
            tokens_after=self._tokens(),
            summarized=len(history),
            kept=len(tail),
            summary_chars=len(summary),
        )
        return Compacted(summary, before, kept_from=kept_from(tail[0]) if tail else None)

    def _cut(self, start: int) -> int | None:
        """Where the kept part begins: about `keep_recent` tokens from the end, at a prompt or at
        a turn that calls tools, so a tool result never loses its call. None keeps nothing."""
        threshold = self._threshold()
        budget = min(self._limits.keep_recent, threshold // 2 if threshold else 1 << 62)
        points = [
            index
            for index in range(start + 1, len(self._conversation))
            if kept_from(self._conversation[index]) is not None
        ]
        size = 0
        for index in range(len(self._conversation) - 1, start, -1):
            size += _estimate_tokens(self._conversation[index])
            if size >= budget:
                return next((point for point in points if point >= index), None)
        return None

    async def brief(self, instruction: str, *, cancel: asyncio.Event) -> str:
        """Write a briefing of the conversation, outside any run, without changing it."""
        history = settled(self._conversation)
        if not history:
            return ""
        request = LlmRequest(
            system=self._context.system(),
            messages=(*to_llm(history), LlmMessage(role="user", content=instruction)),
            tools=self._tools.schemas(),
        )
        for provider in (self._helper, self._provider):
            if provider is None:
                continue
            try:
                text = await self._summarize(
                    request, provider, cancel, tag=BRIEFING_TAG, purpose="briefing"
                )
            except CompactionFailed as error:
                if cancel.is_set() or provider is self._provider:
                    raise BriefingFailed(str(error)) from error
                log.warning("agent.helper_briefing_failed", error=str(error))
                continue
            self.spend("fast" if provider is self._helper else "main", "briefing", Usage(), uses=1)
            return text
        raise BriefingFailed("no model is available")

    async def ask(self, question: str, *, history: bool, main: bool, cancel: asyncio.Event) -> str:
        """Answer one question outside any run, without changing the conversation."""
        past = to_llm(settled(self._conversation)) if history else ()
        request = LlmRequest(
            system=self._context.system(),
            messages=(*past, LlmMessage(role="user", content=question + ASIDE)),
            tools=self._tools.schemas(),
        )
        providers = [self._provider] if main else [p for p in (self._helper, self._provider) if p]
        for provider in providers:
            role = "fast" if provider is self._helper else "main"
            text: list[str] = []
            try:
                async for event in self._events(request, cancel, provider, purpose="ask"):
                    match event:
                        case TextDelta(text=chunk):
                            text.append(chunk)
                        case UsageReport(usage=delta):
                            self.spend(role, "plugin", delta)
                        case _:
                            pass
            except ProviderError as error:
                if cancel.is_set() or provider is self._provider:
                    raise AskFailed(str(error)) from error
                log.warning("agent.helper_ask_failed", error=str(error))
                continue
            self.spend(role, "plugin", Usage(), uses=1)
            answer = "".join(text).strip()
            if not answer:
                raise AskFailed("the model gave no answer")
            return answer
        raise AskFailed("no model is available")

    async def _summarize(
        self,
        request: LlmRequest,
        provider: LLMProvider,
        cancel: asyncio.Event,
        *,
        tag: str = "summary",
        purpose: str = "compact",
    ) -> str:
        text: list[str] = []
        called = False
        cut_off = False
        role = "fast" if provider is self._helper else "main"
        try:
            async for event in self._events(request, cancel, provider, purpose=purpose):
                match event:
                    case TextDelta(text=chunk):
                        text.append(chunk)
                    case ToolCallReady():
                        called = True
                    case Stop(reason="max_tokens"):
                        cut_off = True
                    case UsageReport(usage=delta):
                        if purpose == "compact":
                            self._usage = self._usage + delta
                        self.spend(role, purpose, delta)
                    case _:
                        pass
        except ProviderError as error:
            raise CompactionFailed(str(error)) from error
        summary = extract_tagged("".join(text), tag)
        if cut_off:
            raise CompactionFailed("the summary was cut off at the output limit")
        if cancel.is_set() or called or not summary:
            raise CompactionFailed("the model did not produce a summary")
        return summary

    def _events(
        self,
        request: LlmRequest,
        cancel: asyncio.Event,
        provider: LLMProvider | None = None,
        *,
        purpose: str = "turn",
    ) -> AsyncIterator[LlmEvent]:
        chosen = provider or self._provider
        dumped = self._dump.write(request, purpose) if self._dump is not None else None
        return observed(
            chosen.stream(request, cancel=cancel),
            request,
            purpose=purpose,
            role="fast" if chosen is self._helper else "main",
            dumped=dumped,
        )

    def _next_input(self, *, has_tool_calls: bool) -> list[UserTurn]:
        if self._steer:
            steered = list(self._steer)
            self._steer.clear()
            return steered
        if not has_tool_calls and self._follow_up:
            return [self._follow_up.popleft()]
        return []

    def _resilient(self, provider: LLMProvider) -> ResilientProvider:
        return ResilientProvider(
            provider,
            first_token_timeout_s=self._limits.first_token_timeout_s,
            idle_timeout_s=self._limits.idle_timeout_s,
            retries=self._limits.retries,
            retry_delay_s=self._limits.retry_delay_s,
        )

    def _prompt_parts(self) -> tuple[str, tuple[ToolSchema, ...]]:
        # A run keeps the system prompt and tool list it started with, so MCP servers or skills
        # changing mid-run do not rewrite the request prefix the provider has cached.
        return self._prompt or (self._context.system(), self._tools.schemas())

    def _request(self) -> LlmRequest:
        system, tools = self._prompt_parts()
        return LlmRequest(
            system=system,
            messages=to_llm(self._conversation),
            tools=tools,
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
        asked = time.monotonic()
        ran: float | None = None
        allowed = False
        try:
            verdict = await interruptible(
                self._gate.check(view, subject=prepared.subject, provenance=provenance), cancel
            )
            allowed = verdict.allowed
            if verdict.allowed:
                ran = time.monotonic()
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
        done = time.monotonic()
        log.info(
            "tool.call",
            tool=prepared.name,
            risk=prepared.risk.value,
            allowed=allowed,
            error=result.is_error,
            chars=len(result.content),
            truncated="[truncated " in result.content,
            wait_ms=round(((ran or done) - asked) * 1000),
            run_ms=round((done - ran) * 1000) if ran is not None else None,
        )
        yield ToolEnd(call.id, result)

    async def _invoke(
        self, prepared: PreparedCall, cancel: asyncio.Event, ctx: ToolCtx
    ) -> ToolResult:
        try:
            return await interruptible(prepared.execute(ctx), cancel, self._limits.tool_timeout_s)
        except TimedOut:
            return ToolResult("Tool timed out", is_error=True)
        except (ToolError, SandboxError, OSError, UnicodeError) as error:
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

    def _drop_images(self) -> bool:
        """Forget every image, so one the model cannot read does not fail each later request."""
        dropped = False
        for index, message in enumerate(self._conversation):
            if isinstance(message, UserTurn) and message.images:
                note = f"{message.text}\n\n[{len(message.images)} image(s) removed: unreadable]"
                self._conversation[index] = message.model_copy(update={"images": (), "text": note})
                dropped = True
        return dropped

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

# What a 1568 px image costs on Anthropic, the largest the terminal client sends.
IMAGE_TOKENS = 1600

_UNFINISHED: dict[StopReason, str] = {
    "max_tokens": "Not executed: the response hit the output limit before the call was complete",
    "refusal": "Not executed: the model declined the request",
}


def _estimate_tokens(message: Message) -> int:
    match message:
        case UserTurn(text=text, images=images):
            return len(text) // 4 + IMAGE_TOKENS * len(images)
        case ToolResultTurn(content=text) | SummaryTurn(text=text) | NotesTurn(text=text):
            return len(text) // 4
        case AssistantTurn(text=text, tool_calls=calls):
            return (len(text) + sum(len(_signature(call)) for call in calls)) // 4


def _signature(call: ToolCallRequest) -> str:
    return f"{call.name}:{json.dumps(call.args, sort_keys=True)}"
