import asyncio
import json
from collections import deque
from collections.abc import AsyncIterator, Sequence
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
from plural.agent.messages import AssistantTurn, Message, ToolResultTurn, UserTurn, to_llm
from plural.agent.providers.base import (
    LLMProvider,
    LlmRequest,
    Stop,
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


@dataclass(slots=True)
class _Turn:
    message_id: str
    text: list[str] = field(default_factory=list[str])
    thinking: list[str] = field(default_factory=list[str])
    calls: list[ToolCallRequest] = field(default_factory=list[ToolCallRequest])


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
        usage = Usage()
        recent: deque[str] = deque(maxlen=self._limits.repeat_limit)
        try:
            for _ in range(self._limits.max_turns):
                turn = _Turn(self._ids.new("m_"))
                yield MessageStart(turn.message_id)
                async for event in self._provider.stream(self._request(), cancel=cancel):
                    match event:
                        case TextDelta(text=text):
                            turn.text.append(text)
                            yield MessageDelta(turn.message_id, text, thinking=False)
                        case ThinkingDelta(text=text):
                            turn.thinking.append(text)
                            yield MessageDelta(turn.message_id, text, thinking=True)
                        case ToolCallReady(call=call):
                            turn.calls.append(call)
                        case UsageReport(usage=delta):
                            usage = usage + delta
                        case Stop():
                            pass
                assistant = AssistantTurn(text="".join(turn.text), tool_calls=tuple(turn.calls))
                self._conversation.append(assistant)
                yield MessageEnd(turn.message_id, assistant.text, "".join(turn.thinking))
                if cancel.is_set():
                    yield RunEnd(RunEndReason.ABORTED, usage)
                    return
                for call in assistant.tool_calls:
                    recent.append(_signature(call))
                    if len(recent) == recent.maxlen and len(set(recent)) == 1:
                        yield RunEnd(RunEndReason.LIMIT, usage, "repeated identical tool call")
                        return
                    async for event in self._execute(call, provenance):
                        yield event
                    if cancel.is_set():
                        yield RunEnd(RunEndReason.ABORTED, usage)
                        return
                queued = self._next_input(has_tool_calls=bool(assistant.tool_calls))
                if not assistant.tool_calls and not queued:
                    yield RunEnd(RunEndReason.STOP, usage)
                    return
                for message in queued:
                    provenance = merge(provenance, message.provenance)
                    self._conversation.append(message)
            yield RunEnd(RunEndReason.LIMIT, usage, "max turns reached")
        finally:
            self._settle()

    def _next_input(self, *, has_tool_calls: bool) -> list[UserTurn]:
        if self._steer:
            steered = list(self._steer)
            self._steer.clear()
            return steered
        if not has_tool_calls and self._follow_up:
            return [self._follow_up.popleft()]
        return []

    def _request(self) -> LlmRequest:
        messages = to_llm(self._context.compact(self._conversation))
        return LlmRequest(
            system=self._context.system(), messages=messages, tools=self._tools.schemas()
        )

    async def _execute(
        self, call: ToolCallRequest, provenance: Provenance
    ) -> AsyncIterator[AgentEvent]:
        try:
            prepared = self._tools.prepare(call)
        except (UnknownTool, ValidationError) as error:
            yield ToolStart(
                ToolCallView(id=call.id, name=call.name, risk=ToolRisk.EXEC, args=call.args)
            )
            yield self._finish(call, ToolResult(f"Invalid tool call: {error}", is_error=True))
            return
        view = ToolCallView(
            id=call.id,
            name=prepared.name,
            risk=prepared.risk,
            subject=prepared.subject,
            args=call.args,
        )
        yield ToolStart(view)
        verdict = await self._gate.check(view, subject=prepared.subject, provenance=provenance)
        if verdict.allowed:
            result = await self._invoke(prepared)
        else:
            result = ToolResult(f"Denied: {verdict.reason}", is_error=True)
        yield self._finish(call, result)

    async def _invoke(self, prepared: PreparedCall) -> ToolResult:
        try:
            return await asyncio.wait_for(
                prepared.execute(self._tool_ctx), self._limits.tool_timeout_s
            )
        except TimeoutError:
            return ToolResult("Tool timed out", is_error=True)
        except (ToolError, SandboxError, OSError, UnicodeDecodeError) as error:
            return ToolResult(f"{type(error).__name__}: {error}", is_error=True)

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


def _signature(call: ToolCallRequest) -> str:
    return f"{call.name}:{json.dumps(call.args, sort_keys=True)}"
