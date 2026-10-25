import asyncio
import json
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from typing import Final, cast

import openai
from openai import AsyncOpenAI, omit
from openai.types import CompletionUsage
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallParam,
    ChatCompletionToolParam,
)
from openai.types.chat.chat_completion_chunk import ChoiceDelta, ChoiceDeltaToolCall
from pydantic import JsonValue

from plural.agent.providers.base import (
    Effort,
    LlmEvent,
    LlmMessage,
    LlmRequest,
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

REASONING_FIELDS: Final = ("reasoning_content", "reasoning")

_STOP_REASONS: Final[dict[str, StopReason]] = {
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "length": "max_tokens",
    "content_filter": "refusal",
}


@dataclass(slots=True)
class _PendingCall:
    id: str = ""
    name: str = ""
    arguments: list[str] = field(default_factory=list[str])

    def request(self) -> ToolCallRequest:
        raw = "".join(self.arguments) or "{}"
        try:
            args = json.loads(raw)
        except json.JSONDecodeError as error:
            return ToolCallRequest(id=self.id, name=self.name, parse_error=f"invalid JSON: {error}")
        if not isinstance(args, dict):
            return ToolCallRequest(
                id=self.id, name=self.name, parse_error="arguments are not an object"
            )
        return ToolCallRequest(id=self.id, name=self.name, args=cast("dict[str, JsonValue]", args))


class OpenAIProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        max_tokens: int | None = None,
        effort: Effort | None = None,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self._client = client or AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._max_tokens = max_tokens
        self._effort: Effort | None = effort

    async def stream(
        self, request: LlmRequest, *, cancel: asyncio.Event
    ) -> AsyncIterator[LlmEvent]:
        calls: dict[int, _PendingCall] = {}
        usage = Usage()
        stop: StopReason = "end_turn"
        try:
            chunks = await self._client.chat.completions.create(
                model=self._model,
                messages=to_messages(request.system, request.messages),
                tools=[_tool(schema) for schema in request.tools] or omit,
                stream=True,
                stream_options={"include_usage": True},
                max_completion_tokens=self._max_tokens if self._max_tokens else omit,
                reasoning_effort=self._effort if self._effort else omit,
            )
            async with chunks:
                async for chunk in chunks:
                    if cancel.is_set():
                        return
                    if chunk.usage is not None:
                        usage = _usage(chunk.usage)
                    for choice in chunk.choices:
                        for event in _deltas(choice.delta):
                            yield event
                        _collect(calls, choice.delta.tool_calls or ())
                        if choice.finish_reason is not None:
                            stop = _STOP_REASONS.get(choice.finish_reason, "end_turn")
        except openai.APIError as error:
            raise ProviderError(_describe(error)) from error
        for index in sorted(calls):
            yield ToolCallReady(call=calls[index].request())
        yield UsageReport(usage=usage)
        yield Stop(reason="tool_use" if calls and stop == "end_turn" else stop)


def to_messages(system: str, messages: Iterable[LlmMessage]) -> list[ChatCompletionMessageParam]:
    converted: list[ChatCompletionMessageParam] = [{"role": "system", "content": system}]
    for message in messages:
        match message.role:
            case "user":
                converted.append({"role": "user", "content": message.content})
            case "tool":
                converted.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.tool_call_id or "",
                        "content": message.content,
                    }
                )
            case "assistant":
                if not message.content and not message.tool_calls:
                    continue
                calls: list[ChatCompletionMessageToolCallParam] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": json.dumps(call.args)},
                    }
                    for call in message.tool_calls
                ]
                if calls:
                    converted.append(
                        {
                            "role": "assistant",
                            "content": message.content or None,
                            "tool_calls": calls,
                        }
                    )
                else:
                    converted.append({"role": "assistant", "content": message.content})
    return converted


def _tool(schema: ToolSchema) -> ChatCompletionToolParam:
    return {
        "type": "function",
        "function": {
            "name": schema.name,
            "description": schema.description,
            "parameters": cast("dict[str, object]", schema.parameters),
        },
    }


def _deltas(delta: ChoiceDelta) -> Iterable[LlmEvent]:
    extra = delta.model_extra or {}
    for name in REASONING_FIELDS:
        reasoning = extra.get(name)
        if isinstance(reasoning, str) and reasoning:
            yield ThinkingDelta(text=reasoning)
            break
    if delta.content:
        yield TextDelta(text=delta.content)


def _collect(calls: dict[int, _PendingCall], fragments: Iterable[ChoiceDeltaToolCall]) -> None:
    for fragment in fragments:
        pending = calls.setdefault(fragment.index, _PendingCall())
        if fragment.id:
            pending.id = fragment.id
        if fragment.function is None:
            continue
        if fragment.function.name:
            pending.name = fragment.function.name
        if fragment.function.arguments:
            pending.arguments.append(fragment.function.arguments)


def _usage(usage: CompletionUsage) -> Usage:
    details = usage.prompt_tokens_details
    cached = (details.cached_tokens or 0) if details is not None else 0
    return Usage(
        input_tokens=usage.prompt_tokens - cached,
        output_tokens=usage.completion_tokens,
        cache_read_tokens=cached,
    )


def _describe(error: openai.APIError) -> str:
    if isinstance(error, openai.APIStatusError):
        return f"openai {error.status_code}: {error.message}"
    return f"openai: {type(error).__name__}"
