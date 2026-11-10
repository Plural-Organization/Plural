import asyncio
import re
from collections import deque
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field, replace

import structlog

from plural.agent.context.briefing import BRIEFING_TAG
from plural.agent.context.compaction import (
    SUMMARY_SYSTEM,
    CompactionFailed,
    compacted,
    cut,
    summary_request,
    with_files,
)
from plural.agent.context.context import ContextBuilder, system_text
from plural.agent.context.meter import Sections, context_parts, estimate_tokens, signature
from plural.agent.context.telemetry import RequestDump, hit_rate
from plural.agent.loop.events import (
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
    ToolsLoaded,
)
from plural.agent.loop.gate import PolicyGate
from plural.agent.loop.messages import (
    HARNESS_SOURCE,
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
from plural.agent.loop.models import Models
from plural.agent.loop.tool_runner import ToolRunner
from plural.agent.prompts import prompt
from plural.agent.providers.base import (
    ContextOverflow,
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
from plural.agent.tools.base import ToolCtx, ToolResult
from plural.agent.tools.registry import ToolRegistry
from plural.agent.tracing import INPUT_CHARS, OUTPUT_CHARS, Span, Tracer, clip
from plural.core.ports import IdGenerator
from plural.core.provenance import merge
from plural.protocol.models import (
    ContextPart,
    Origin,
    Provenance,
    Role,
    RunEndReason,
    SpanKind,
    SpanStatus,
    Usage,
)

log = structlog.get_logger(__name__)


# How often in a row a run reminds the model that it stopped at a promise; a turn with tool
# calls starts the count again, so a model that keeps going is never cut off by an old count.
MAX_NUDGES = 2
NUDGE = (
    "Your last answer had no tool calls, so nothing ran: saying a call was made does not make "
    "it. Put each call you need in tool_calls now, with its name and args. If the work is "
    "already done, give your final answer with no tool calls."
)
# A short reply that ends on what the model is about to do: "I'll read pages.py next."
_PROMISE = re.compile(
    r"(?:^|[.!?:\n]\s*)(?:I['’]ll|I will|I am going to|I['’]m going to|Let me|Next,? I|"
    r"Now I['’]ll|I['’]m waiting|I am waiting)\b",
    re.IGNORECASE,
)


def promises(text: str) -> bool:
    """A reply that announces work instead of reporting it. A long reply is a report even when
    it says what comes next, so only short ones count."""
    reply = text.strip()
    return 0 < len(reply) <= 600 and _PROMISE.search(reply[-300:]) is not None


class BriefingFailed(Exception):
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
        tracer: Tracer | None = None,
        span: Span | None = None,
        role: str = "main",
    ) -> None:
        self._tools = tools
        self._gate = gate
        self._context = context
        self._tool_ctx = tool_ctx
        self._ids = ids
        self._limits = limits or LoopLimits()
        self._models = Models(provider, helper, wrap=self._resilient, dump=dump, main_role=role)
        self._tracer = tracer or Tracer()
        # A sub-agent's loop works under the span of the call that started it.
        self._under = span
        self._prompt: tuple[Sections, tuple[ToolSchema, ...]] | None = None
        self._conversation: list[Message] = []
        self._notes: list[NotesTurn] = []
        self._shared = False
        self._steer: deque[UserTurn] = deque()
        self._follow_up: deque[UserTurn] = deque()
        self._usage = Usage()
        # The prompt size the provider last reported, and how many messages that prompt held.
        self._context_tokens = 0
        self._measured = 0
        # The share of the latest request read from the provider's cache.
        self._hit: float | None = None
        self._window = self._limits.context_window
        self._compact_requested = False
        self._compaction_failed = False
        self._verify_compaction = False
        self._runner = ToolRunner(
            tools=tools, gate=gate, tool_ctx=tool_ctx, timeout_s=self._limits.tool_timeout_s
        )
        # The registry's revision the run's tool list was taken at.
        self._revision = tools.revision

    def spend(self, role: str, who: str, usage: Usage, *, uses: int = 0) -> None:
        self._models.spend(role, who, usage, uses=uses)

    def take_spending(self) -> tuple[Spend, ...]:
        return self._models.take_spending()

    @property
    def provider(self) -> LLMProvider:
        return self._models.main.inner

    @property
    def helper(self) -> LLMProvider | None:
        return self._models.helper.inner if self._models.helper is not None else None

    @property
    def dump(self) -> RequestDump | None:
        return self._models.dump

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
        self._models.swap(provider, helper)
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
        await self._models.close()

    def request_compaction(self) -> None:
        self._compact_requested = True

    def fill(self) -> ContextFill:
        window = self._window or FALLBACK_WINDOW
        tokens = self._tokens()
        return ContextFill(
            tokens, window, self._threshold_of(window) / window, self._parts(tokens), self._hit
        )

    @property
    def can_compact(self) -> bool:
        return len(self._conversation) >= 2

    async def compact(self, *, cancel: asyncio.Event) -> AsyncIterator[AgentEvent]:
        """Summarize the conversation now, outside a prompt, so everyone sees it happen."""
        self._usage = Usage()
        span = self._begin("compact", "")
        yield Compacting(self._tokens())
        try:
            yield await self._compact(None, cancel, "manual")
        except CompactionFailed as error:
            self._end(span, RunEndReason.ERROR, str(error))
            yield RunEnd(RunEndReason.ERROR, self._usage, f"compaction failed: {error}")
            return
        yield self.fill()
        reason = RunEndReason.ABORTED if cancel.is_set() else RunEndReason.STOP
        self._end(span, reason, "")
        yield RunEnd(reason, self._usage)

    @property
    def tracer(self) -> Tracer:
        return self._tracer

    def _begin(self, name: str, detail: str) -> Span:
        """Open the run's span, the one its model and tool calls go under."""
        span = self._under or self._tracer.start(SpanKind.RUN, name, detail=detail)
        self._models.span = span
        self._runner.span = span
        return span

    def _end(self, span: Span, reason: RunEndReason | None, error: str | None) -> None:
        self._models.span = None
        self._runner.span = None
        if span is self._under:
            return
        status = (
            SpanStatus.OK
            if reason is RunEndReason.STOP
            else SpanStatus.CANCELLED
            if reason is RunEndReason.ABORTED or reason is None
            else SpanStatus.ERROR
        )
        span.end(status, error=(error or "")[:300])
        self._tracer.settle()

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
        """One run: model turns and their tool calls, until the model stops or a limit ends it."""
        span = self._begin("run", " ".join(prompt.text.split())[:200])
        if span is not self._under:
            span.set(input=clip(prompt.text, INPUT_CHARS))
        ending: RunEnd | None = None
        try:
            async for event in self._run(prompt, cancel):
                if isinstance(event, MessageEnd) and event.text.strip() and span is not self._under:
                    span.set(output=clip(event.text, OUTPUT_CHARS))
                if isinstance(event, RunEnd):
                    # Closed before the event goes out, so whoever sees the run end sees it whole.
                    ending = event
                    self._end(span, event.reason, event.error)
                yield event
        finally:
            if ending is None:
                self._end(span, None, None)

    async def _run(self, prompt: UserTurn, cancel: asyncio.Event) -> AsyncIterator[AgentEvent]:
        provenance = merge(prompt.provenance, SHARED) if self._shared else prompt.provenance
        self._conversation.extend(self._notes)
        self._notes.clear()
        self._conversation.append(prompt)
        self._usage = Usage()
        self.spend("main", "", Usage(), uses=1)
        self._gate.begin_run()
        self._prompt = (self._context.sections(), self._tools.schemas())
        self._revision = self._tools.revision
        self._compaction_failed = False
        self._verify_compaction = False
        recovering = False
        nudges = 0
        recent: deque[str] = deque(maxlen=self._limits.repeat_limit)
        try:
            for _ in range(self._limits.max_turns):
                if self._should_compact():
                    async for event in self._compact_when_due(prompt, cancel):
                        yield event
                    if cancel.is_set():
                        yield RunEnd(RunEndReason.ABORTED, self._usage)
                        return
                turn = _Turn(self._ids.new("m_"))
                yield MessageStart(turn.message_id)
                try:
                    async for event in self._model_turn(turn, cancel):
                        yield event
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
                        start, end = self._runner.skip(call, _UNFINISHED[turn.stop])
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
                async for event in self._run_tools(
                    assistant.tool_calls, provenance, cancel, recent
                ):
                    if isinstance(event, ToolEnd):
                        ended.append(event.result)
                    yield event
                    if isinstance(event, RunEnd):
                        return
                if fresh := self._declare_loaded_tools():
                    yield ToolsLoaded(fresh)
                # Tools that all ask to terminate hand the turn back without another model call.
                has_tool_calls = bool(ended) and not all(result.terminate for result in ended)
                if has_tool_calls:
                    nudges = 0
                if (has_tool_calls or self._steer or self._follow_up) and (
                    limit := self._gate.turn_limit(usage=self._usage, provenance=provenance)
                ):
                    yield RunEnd(RunEndReason.LIMIT, self._usage, limit)
                    return
                queued = self._next_input(has_tool_calls=has_tool_calls)
                if (
                    not has_tool_calls
                    and not queued
                    and nudges < MAX_NUDGES
                    and promises(assistant.text)
                ):
                    # The model said what it would do and called nothing: a small model behind a
                    # JSON answer does this, thinking the tools run on their own. One reminder
                    # instead of ending the run on a promise.
                    nudges += 1
                    log.info("agent.nudged", text=assistant.text[:200])
                    self._conversation.append(NotesTurn(source=HARNESS_SOURCE, text=NUDGE))
                    continue
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

    async def _compact_when_due(
        self, prompt: UserTurn, cancel: asyncio.Event
    ) -> AsyncIterator[AgentEvent]:
        """Summarize before the next model call; a failure is logged and the run goes on."""
        reason = "requested" if self._compact_requested else "threshold"
        yield Compacting(self._tokens())
        try:
            yield await self._compact(prompt, cancel, reason)
            yield self.fill()
        except CompactionFailed as error:
            self._compaction_failed = True
            log.warning("agent.compaction_failed", error=str(error))

    async def _model_turn(self, turn: _Turn, cancel: asyncio.Event) -> AsyncIterator[AgentEvent]:
        """One model call: its text and thinking go out as deltas, the rest is kept in `turn`."""
        measured = len(self._conversation)
        async for event in self._models.stream(self._request(), cancel):
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
                case UsageReport(usage=delta, last=last):
                    self._usage = self._usage + delta
                    self.spend("main", "", delta)
                    current = last or delta
                    if current.prompt_tokens:
                        self._context_tokens = current.prompt_tokens
                        self._measured = measured
                        self._hit = hit_rate(current)
                        self._check_compaction_helped()
                    yield self.fill()
                case Stop(reason=reason):
                    turn.stop = reason

    async def _run_tools(
        self,
        calls: Sequence[ToolCallRequest],
        provenance: Provenance,
        cancel: asyncio.Event,
        recent: deque[str],
    ) -> AsyncIterator[AgentEvent]:
        """Run a turn's tool calls and record their results. A `RunEnd` is the last event when
        the run must stop here: the same call repeated too often, or the run was cancelled."""
        for group in self._runner.groups(calls):
            for call in group:
                recent.append(signature(call))
                if len(recent) == recent.maxlen and len(set(recent)) == 1:
                    yield RunEnd(RunEndReason.LIMIT, self._usage, "repeated identical tool call")
                    return
            results: dict[str, ToolResult] = {}
            async for event in self._runner.run_group(group, provenance, cancel):
                if isinstance(event, ToolEnd):
                    results[event.call_id] = event.result
                    if len(group) == 1:
                        self._answer(group[0], event.result)
                yield event
            if len(group) > 1:
                # Calls that ran side by side are answered in the order the model made them.
                for call in group:
                    if call.id in results:
                        self._answer(call, results[call.id])
            if cancel.is_set():
                yield RunEnd(RunEndReason.ABORTED, self._usage)
                return

    def _declare_loaded_tools(self) -> tuple[str, ...]:
        """Tools loaded this turn are declared from the next model call on; their names."""
        if self._prompt is None or self._tools.revision == self._revision:
            return ()
        self._revision = self._tools.revision
        known = {schema.name for schema in self._prompt[1]}
        schemas = self._tools.schemas()
        self._prompt = (self._prompt[0], schemas)
        return tuple(schema.name for schema in schemas if schema.name not in known)

    def _threshold_of(self, window: int) -> int:
        # A window smaller than twice the reserve still gets half of itself for the conversation.
        return max(window - self._limits.compact_reserve, window // 2)

    def _threshold(self) -> int | None:
        """The size at which the conversation is summarized; None before the window is known."""
        return self._threshold_of(self._window) if self._window is not None else None

    def _tokens(self) -> int:
        """The provider's last count of the prompt, plus an estimate of what came after it."""
        added = self._conversation[self._measured :]
        return self._context_tokens + sum(estimate_tokens(message) for message in added)

    async def _learn_window(self) -> None:
        if self._limits.context_window is not None:
            return
        ask = getattr(self._models.main.inner, "context_window", None)
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
        threshold = self._threshold()
        budget = min(self._limits.keep_recent, threshold // 2 if threshold else 1 << 62)
        end = cut(self._conversation, start, budget) or len(self._conversation)
        history = self._conversation[start:end]
        request = LlmRequest(
            system=SUMMARY_SYSTEM,
            messages=(LlmMessage(role="user", content=summary_request(history, previous)),),
        )
        summary, role = await self._models.tagged(
            request, cancel, tag="summary", purpose="compact", counted=self._count
        )
        summary = with_files(summary, history, previous)
        tail = self._conversation[end:]
        before = self._tokens()
        self._conversation = compacted(summary, tail, prompt)
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
        try:
            text, _ = await self._models.tagged(
                request, cancel, tag=BRIEFING_TAG, purpose="briefing"
            )
        except CompactionFailed as error:
            raise BriefingFailed(str(error)) from error
        return text

    async def ask(self, question: str, *, history: bool, main: bool, cancel: asyncio.Event) -> str:
        """Answer one question outside any run, without changing the conversation."""
        past = to_llm(settled(self._conversation)) if history else ()
        request = LlmRequest(
            system=self._context.system(),
            messages=(*past, LlmMessage(role="user", content=question + ASIDE)),
            tools=self._tools.schemas(),
        )
        return await self._models.answer(request, cancel, main=main)

    def _count(self, usage: Usage) -> None:
        self._usage = self._usage + usage

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

    def _prompt_parts(self) -> tuple[Sections, tuple[ToolSchema, ...]]:
        # A run keeps the system prompt and tool list it started with, so MCP servers or skills
        # changing mid-run do not rewrite the request prefix the provider has cached.
        return self._prompt or (self._context.sections(), self._tools.schemas())

    def _parts(self, tokens: int) -> tuple[ContextPart, ...]:
        sections, tools = self._prompt_parts()
        return context_parts(
            sections, tools, self._conversation, tokens=tokens, counted=bool(self._context_tokens)
        )

    def _request(self) -> LlmRequest:
        sections, tools = self._prompt_parts()
        return LlmRequest(
            system=system_text(sections),
            messages=to_llm(self._conversation),
            tools=tools,
        )

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


_UNFINISHED: dict[StopReason, str] = {
    "max_tokens": "Not executed: the response hit the output limit before the call was complete",
    "refusal": "Not executed: the model declined the request",
}
