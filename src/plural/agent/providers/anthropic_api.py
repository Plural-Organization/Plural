import asyncio
from collections.abc import AsyncIterator, Iterable
from typing import Final, Literal, cast

import anthropic
from anthropic import AsyncAnthropic, omit
from anthropic.types.beta import (
    BetaContentBlockParam,
    BetaMessage,
    BetaMessageParam,
    BetaRawContentBlockDeltaEvent,
    BetaTextDelta,
    BetaThinkingDelta,
    BetaToolParam,
    BetaToolUseBlockParam,
    BetaUsage,
)
from pydantic import JsonValue

from plural.agent.providers.base import (
    ContextOverflow,
    Effort,
    LlmEvent,
    LlmMessage,
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
    ToolSchema,
    UsageReport,
)
from plural.protocol.models import Usage

PROVIDER: Final = "anthropic"
DEFAULT_MODEL: Final = "claude-opus-5-5"
DEFAULT_MAX_TOKENS: Final = 64_000
FALLBACK_BETA: Final = "server-side-fallback-2026-07-01"
FALLBACK_MODELS: Final = frozenset(
    {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
)

_STOP_REASONS: Final[dict[str, StopReason]] = {
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "model_context_window_exceeded": "max_tokens",
    "refusal": "refusal",
}


class AnthropicProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        effort: Effort | None = None,
        base_url: str | None = None,
        client: AsyncAnthropic | None = None,
    ) -> None:
        self._client = client or AsyncAnthropic(api_key=api_key, base_url=base_url)
        self._model = model
        self._max_tokens = max_tokens
        self._effort: Effort | None = effort

    async def stream(
        self, request: LlmRequest, *, cancel: asyncio.Event
    ) -> AsyncIterator[LlmEvent]:
        fallback = self._model in FALLBACK_MODELS
        try:
            async with self._client.beta.messages.stream(
                model=self._model,
                max_tokens=self._max_tokens,
                system=[{"type": "text", "text": request.system}],
                messages=to_messages(request.messages),
                tools=[_tool(schema) for schema in request.tools] or omit,
                cache_control={"type": "ephemeral"},
                thinking={"type": "adaptive", "display": "summarized"},
                output_config={"effort": self._effort} if self._effort else omit,
                fallbacks="default" if fallback else omit,
                betas=[FALLBACK_BETA] if fallback else omit,
            ) as stream:
                async for event in stream:
                    if cancel.is_set():
                        return
                    match event:
                        case BetaRawContentBlockDeltaEvent(delta=BetaTextDelta(text=text)):
                            yield TextDelta(text=text)
                        case BetaRawContentBlockDeltaEvent(
                            delta=BetaThinkingDelta(thinking=text)
                        ) if text:
                            yield ThinkingDelta(text=text)
                        case _:
                            pass
                message = await stream.get_final_message()
        except anthropic.APIError as error:
            if _overflows(error):
                raise ContextOverflow(_describe(error)) from error
            raise ProviderError(_describe(error)) from error
        for event in _finish(message):
            yield event


def to_messages(messages: Iterable[LlmMessage]) -> list[BetaMessageParam]:
    merged: list[BetaMessageParam] = []
    for message in messages:
        role: Literal["user", "assistant"] = "assistant" if message.role == "assistant" else "user"
        blocks = _blocks(message)
        if not blocks:
            continue
        if merged and merged[-1]["role"] == role:
            previous = cast("list[BetaContentBlockParam]", merged[-1]["content"])
            previous.extend(blocks)
        else:
            merged.append(_message(role, blocks))
    return merged


def _message(
    role: Literal["user", "assistant"], blocks: list[BetaContentBlockParam]
) -> BetaMessageParam:
    if role == "assistant":
        return {"role": "assistant", "content": blocks}
    return {"role": "user", "content": blocks}


def _blocks(message: LlmMessage) -> list[BetaContentBlockParam]:
    match message.role:
        case "user":
            return [{"type": "text", "text": message.content}]
        case "tool":
            return [
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id or "",
                    "content": message.content,
                    "is_error": message.is_error,
                }
            ]
        case "assistant":
            if message.native is not None and message.native.provider == PROVIDER:
                return cast("list[BetaContentBlockParam]", list(message.native.blocks))
            blocks: list[BetaContentBlockParam] = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            blocks.extend(_tool_use(call) for call in message.tool_calls)
            return blocks


def _tool_use(call: ToolCallRequest) -> BetaToolUseBlockParam:
    args = cast("dict[str, object]", call.args)
    return {"type": "tool_use", "id": call.id, "name": call.name, "input": args}


def _tool(schema: ToolSchema) -> BetaToolParam:
    return {
        "name": schema.name,
        "description": schema.description,
        "input_schema": cast("dict[str, object]", schema.parameters),
    }


def _finish(message: BetaMessage) -> Iterable[LlmEvent]:
    for block in message.content:
        if block.type == "tool_use":
            yield ToolCallReady(call=_call(block.id, block.name, block.input))
    blocks = tuple(
        cast("JsonValue", block.model_dump(mode="json", exclude_none=True))
        for block in message.content
    )
    yield NativeReady(content=NativeContent(provider=PROVIDER, blocks=blocks))
    yield UsageReport(usage=_usage(message.usage))
    yield Stop(reason=_STOP_REASONS.get(message.stop_reason or "", "end_turn"))


def _call(call_id: str, name: str, raw: object) -> ToolCallRequest:
    if not isinstance(raw, dict):
        return ToolCallRequest(id=call_id, name=name, parse_error="arguments are not an object")
    return ToolCallRequest(id=call_id, name=name, args=cast("dict[str, JsonValue]", raw))


def _usage(usage: BetaUsage) -> Usage:
    return Usage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_input_tokens or 0,
        cache_write_tokens=usage.cache_creation_input_tokens or 0,
    )


def _overflows(error: anthropic.APIError) -> bool:
    return isinstance(error, anthropic.BadRequestError) and "prompt is too long" in error.message


def _describe(error: anthropic.APIError) -> str:
    if isinstance(error, anthropic.APIStatusError):
        return f"anthropic {error.status_code}: {error.message}"
    return f"anthropic: {type(error).__name__}"
