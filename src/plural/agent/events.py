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
class ToolOutput:
    call_id: str
    chunk: str


@dataclass(frozen=True, slots=True)
class ToolEnd:
    call_id: str
    result: ToolResult


@dataclass(frozen=True, slots=True)
class Compacted:
    summary: str
    tokens_before: int


@dataclass(frozen=True, slots=True)
class Compacting:
    tokens_before: int


@dataclass(frozen=True, slots=True)
class ContextFill:
    tokens: int
    window: int
    compact_at: float


@dataclass(frozen=True, slots=True)
class ToolsLoaded:
    names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Delivered:
    prompt_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Spend:
    """Tokens one model spent in a run, for the main conversation, a summary or a sub-agent."""

    role: str
    who: str
    usage: Usage
    uses: int = 1


@dataclass(frozen=True, slots=True)
class RunEnd:
    reason: RunEndReason
    usage: Usage
    error: str | None = None


AgentEvent = (
    MessageStart
    | MessageDelta
    | MessageEnd
    | ToolStart
    | ToolOutput
    | ToolEnd
    | Compacting
    | Compacted
    | ContextFill
    | Delivered
    | ToolsLoaded
    | RunEnd
)
