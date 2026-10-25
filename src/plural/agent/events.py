from dataclasses import dataclass

from plural.agent.tools.base import ToolResult
from plural.protocol.models import RunEndReason, ToolCallView, Usage


@dataclass(frozen=True, slots=True)
class MessageStart:
    message_id: str


@dataclass(frozen=True, slots=True)
class MessageDelta:
    message_id: str
    text: str
    thinking: bool


@dataclass(frozen=True, slots=True)
class MessageEnd:
    message_id: str
    text: str
    thinking: str


@dataclass(frozen=True, slots=True)
class ToolStart:
    call: ToolCallView


@dataclass(frozen=True, slots=True)
class ToolEnd:
    call_id: str
    result: ToolResult


@dataclass(frozen=True, slots=True)
class Compacted:
    summary: str
    tokens_before: int


@dataclass(frozen=True, slots=True)
class RunEnd:
    reason: RunEndReason
    usage: Usage
    error: str | None = None


AgentEvent = MessageStart | MessageDelta | MessageEnd | ToolStart | ToolEnd | Compacted | RunEnd
