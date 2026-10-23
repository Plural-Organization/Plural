import asyncio
from collections.abc import AsyncIterator
from typing import Literal, Protocol

from pydantic import Field, JsonValue

from plural.protocol.models import Model, Usage


class ToolCallRequest(Model):
    id: str
    name: str
    args: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])


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


class LlmRequest(Model):
    system: str
    messages: tuple[LlmMessage, ...]
    tools: tuple[ToolSchema, ...] = ()


class TextDelta(Model):
    kind: Literal["text_delta"] = "text_delta"
    text: str


class ThinkingDelta(Model):
    kind: Literal["thinking_delta"] = "thinking_delta"
    text: str


class ToolCallReady(Model):
    kind: Literal["tool_call"] = "tool_call"
    call: ToolCallRequest


class UsageReport(Model):
    kind: Literal["usage"] = "usage"
    usage: Usage


class Stop(Model):
    kind: Literal["stop"] = "stop"
    reason: Literal["end_turn", "tool_use", "max_tokens"] = "end_turn"


LlmEvent = TextDelta | ThinkingDelta | ToolCallReady | UsageReport | Stop


class ProviderError(Exception):
    pass


class LLMProvider(Protocol):
    def stream(self, request: LlmRequest, *, cancel: asyncio.Event) -> AsyncIterator[LlmEvent]: ...
