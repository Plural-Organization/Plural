import asyncio
from collections.abc import AsyncIterator
from typing import Final, Literal, Protocol

from pydantic import Field, JsonValue

from plural.protocol.models import Model, Usage


class ToolCallRequest(Model):
    id: str
    name: str
    args: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    parse_error: str | None = None


class NativeContent(Model):
    provider: str
    blocks: tuple[JsonValue, ...]


class ToolSchema(Model):
    name: str
    description: str
    parameters: dict[str, JsonValue]


class LlmMessage(Model):
    role: Literal["user", "assistant", "tool"]
    content: str
    tool_calls: tuple[ToolCallRequest, ...] = ()
    tool_call_id: str | None = None
    is_error: bool = False
    native: NativeContent | None = None


class LlmRequest(Model):
    system: str
    messages: tuple[LlmMessage, ...]
    tools: tuple[ToolSchema, ...] = ()


StopReason = Literal["end_turn", "tool_use", "max_tokens", "refusal"]

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class TextDelta(Model):
    kind: Literal["text_delta"] = "text_delta"
    text: str


class ThinkingDelta(Model):
    kind: Literal["thinking_delta"] = "thinking_delta"
    text: str


class ProviderActivity(Model):
    """Real provider progress that does not contain user-visible content."""

    kind: Literal["activity"] = "activity"
    source: str


class ToolCallReady(Model):
    kind: Literal["tool_call"] = "tool_call"
    call: ToolCallRequest


class NativeReady(Model):
    kind: Literal["native"] = "native"
    content: NativeContent


class UsageReport(Model):
    kind: Literal["usage"] = "usage"
    usage: Usage


class Stop(Model):
    kind: Literal["stop"] = "stop"
    reason: StopReason = "end_turn"


LlmEvent = (
    TextDelta | ThinkingDelta | ProviderActivity | ToolCallReady | NativeReady | UsageReport | Stop
)


class ProviderError(Exception):
    pass


class ContextOverflow(ProviderError):
    pass


class ProviderBusy(ProviderError):
    pass


RETRYABLE_STATUS: Final = frozenset({408, 409, 429})


def is_retryable_status(status: int) -> bool:
    return status in RETRYABLE_STATUS or status >= 500


class LLMProvider(Protocol):
    def stream(self, request: LlmRequest, *, cancel: asyncio.Event) -> AsyncIterator[LlmEvent]: ...
