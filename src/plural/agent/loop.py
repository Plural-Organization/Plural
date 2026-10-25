import asyncio
import json
from collections import deque
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from dataclasses import dataclass, field

from pydantic import ValidationError

from plural.agent.context import ContextBuilder
from plural.agent.events import (
    AgentEvent,
    MessageDelta,
    MessageEnd,
    MessageStart,
    RunEnd,
    ToolEnd,
    ToolStart,
)
from plural.agent.gate import PolicyGate
from plural.agent.interrupt import Interrupted, TimedOut, interruptible
from plural.agent.messages import AssistantTurn, Message, ToolResultTurn, UserTurn, to_llm
from plural.agent.providers.base import (
    LlmEvent,
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


@dataclass(frozen=True, slots=True)
class LoopLimits:
    max_turns: int = 50
    repeat_limit: int = 3
    tool_timeout_s: float = 600.0
    first_token_timeout_s: float = 120.0
    idle_timeout_s: float = 60.0


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

    def drain_pending(self) -> list[UserTurn]:
        pending = [*self._steer, *self._follow_up]
        self._steer.clear()
        self._follow_up.clear()
        return pending

    async def run(self, prompt: UserTurn, *, cancel: asyncio.Event) -> AsyncIterator[AgentEvent]:
        provenance = prompt.provenance
        self._conversation.append(prompt)
        self._usage = Usage()
        recent: deque[str] = deque(maxlen=self._limits.repeat_limit)
        try:
            for _ in range(self._limits.max_turns):
                turn = _Turn(self._ids.new("m_"))
                yield MessageStart(turn.message_id)
                try:
                    async for event in self._events(cancel):
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
                            case Stop(reason=reason):
                                turn.stop = reason
                except ProviderError as error:
                    yield MessageEnd(turn.message_id, "".join(turn.text), "".join(turn.thinking))
                    yield RunEnd(RunEndReason.ERROR, self._usage, str(error))
                    return
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
                for message in queued:
                    provenance = merge(provenance, message.provenance)
                    self._conversation.append(message)
            yield RunEnd(RunEndReason.LIMIT, self._usage, "max turns reached")
        finally:
            self._settle()

    async def _events(self, cancel: asyncio.Event) -> AsyncIterator[LlmEvent]:
        stream = self._provider.stream(self._request(), cancel=cancel).__aiter__()
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
                result = await self._invoke(prepared, cancel)
            else:
                result = ToolResult(f"Denied: {verdict.reason}", is_error=True)
        except Interrupted:
            result = ToolResult(_ABORTED, is_error=True)
        yield self._finish(call, result)

    async def _invoke(self, prepared: PreparedCall, cancel: asyncio.Event) -> ToolResult:
        try:
            return await interruptible(
                prepared.execute(self._tool_ctx), cancel, self._limits.tool_timeout_s
            )
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
