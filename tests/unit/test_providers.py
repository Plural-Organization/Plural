import asyncio
import json
from collections.abc import Callable
from typing import Any

import anthropic
import httpx2
import openai
import pytest

from plural.agent.providers.anthropic_api import FALLBACK_BETA, AnthropicProvider
from plural.agent.providers.anthropic_api import to_messages as anthropic_messages
from plural.agent.providers.base import (
    ContextOverflow,
    LlmEvent,
    LlmImage,
    LlmMessage,
    LlmRequest,
    NativeContent,
    NativeReady,
    ProviderError,
    Stop,
    TextDelta,
    ThinkingDelta,
    ToolCallReady,
    ToolCallRequest,
    ToolSchema,
    UsageReport,
)
from plural.agent.providers.openai_compat import OpenAIProvider
from plural.agent.providers.openai_compat import to_messages as openai_messages
from plural.protocol.models import Usage

type Handler = Callable[[httpx2.Request], httpx2.Response]

REQUEST = LlmRequest(
    system="be careful",
    messages=(LlmMessage(role="user", content="[Host]\nread a.txt"),),
    tools=(
        ToolSchema(
            name="read",
            description="Read a file",
            parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        ),
    ),
)


class Recorder:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        self.payloads: list[dict[str, Any]] = []
        self.headers: list[httpx2.Headers] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.payloads.append(json.loads(request.content))
        self.headers.append(request.headers)
        return httpx2.Response(
            self.status, text=self.body, headers={"content-type": "text/event-stream"}
        )


def plain(value: object) -> Any:
    return json.loads(json.dumps(value))


def sse(*events: dict[str, Any]) -> str:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)


def chunks(*payloads: dict[str, Any]) -> str:
    lines = [f"data: {json.dumps(p)}\n\n" for p in payloads]
    return "".join([*lines, "data: [DONE]\n\n"])


def anthropic_provider(handler: Handler, model: str = "claude-opus-5-5") -> AnthropicProvider:
    client = anthropic.AsyncAnthropic(
        api_key="test",
        max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    return AnthropicProvider(api_key="test", model=model, client=client)


def openai_provider(handler: Handler) -> OpenAIProvider:
    client = openai.AsyncOpenAI(
        api_key="test",
        base_url="http://local.test/v1",
        max_retries=0,
        http_client=openai.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    return OpenAIProvider(api_key="test", model="qwen", client=client)


async def drain(provider: AnthropicProvider | OpenAIProvider) -> list[LlmEvent]:
    return [event async for event in provider.stream(REQUEST, cancel=asyncio.Event())]


ANTHROPIC_TOOL_TURN = sse(
    {
        "type": "message_start",
        "message": {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 12, "output_tokens": 1},
        },
    },
    {
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "thinking", "thinking": "", "signature": ""},
    },
    {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "thinking_delta", "thinking": "plan"},
    },
    {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "signature_delta", "signature": "sig"},
    },
    {"type": "content_block_stop", "index": 0},
    {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "Reading"}},
    {"type": "content_block_stop", "index": 1},
    {
        "type": "content_block_start",
        "index": 2,
        "content_block": {"type": "tool_use", "id": "toolu_1", "name": "read", "input": {}},
    },
    {
        "type": "content_block_delta",
        "index": 2,
        "delta": {"type": "input_json_delta", "partial_json": '{"path": "a.txt"}'},
    },
    {"type": "content_block_stop", "index": 2},
    {
        "type": "message_delta",
        "delta": {"stop_reason": "tool_use", "stop_sequence": None},
        "usage": {
            "input_tokens": 12,
            "output_tokens": 30,
            "cache_read_input_tokens": 400,
            "cache_creation_input_tokens": 50,
        },
    },
    {"type": "message_stop"},
)


async def test_anthropic_stream_normalizes_events() -> None:
    recorder = Recorder(200, ANTHROPIC_TOOL_TURN)
    events = await drain(anthropic_provider(recorder))

    assert [e for e in events if isinstance(e, ThinkingDelta)] == [ThinkingDelta(text="plan")]
    assert [e for e in events if isinstance(e, TextDelta)] == [TextDelta(text="Reading")]
    calls = [e.call for e in events if isinstance(e, ToolCallReady)]
    assert calls == [ToolCallRequest(id="toolu_1", name="read", args={"path": "a.txt"})]
    usage = next(e.usage for e in events if isinstance(e, UsageReport))
    assert usage == Usage(
        input_tokens=12, output_tokens=30, cache_read_tokens=400, cache_write_tokens=50
    )
    assert events[-1] == Stop(reason="tool_use")
    native = next(e.content for e in events if isinstance(e, NativeReady))
    assert native.provider == "anthropic"
    assert [b["type"] for b in native.blocks if isinstance(b, dict)] == [
        "thinking",
        "text",
        "tool_use",
    ]


async def test_anthropic_request_shape() -> None:
    recorder = Recorder(200, ANTHROPIC_TOOL_TURN)
    await drain(anthropic_provider(recorder))
    payload = recorder.payloads[0]

    assert payload["model"] == "claude-opus-5-5"
    assert payload["cache_control"] == {"type": "ephemeral"}
    assert payload["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert payload["fallbacks"] == "default"
    assert FALLBACK_BETA in recorder.headers[0]["anthropic-beta"]
    assert payload["tools"][0]["input_schema"]["properties"] == {"path": {"type": "string"}}
    assert "temperature" not in payload
    assert recorder.headers[0]["authorization"] == "Bearer test"


async def test_anthropic_oauth_uses_bearer_auth_without_claiming_to_be_claude_code() -> None:
    recorder = Recorder(200, ANTHROPIC_TOOL_TURN)
    client = anthropic.AsyncAnthropic(
        api_key=None,
        auth_token="sk-ant-oat-test",
        max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(recorder)),
    )
    provider = AnthropicProvider(api_key="sk-ant-oat-test", client=client, oauth=True)
    events = await drain(provider)
    payload = recorder.payloads[0]
    assert payload["system"] == [{"type": "text", "text": REQUEST.system}]
    assert payload["tools"][0]["name"] == "read"
    assert "claude-code-20250219" not in recorder.headers[0]["anthropic-beta"]
    assert "oauth-2025-04-20" in recorder.headers[0]["anthropic-beta"]
    assert recorder.headers[0]["authorization"] == "Bearer sk-ant-oat-test"
    assert not recorder.headers[0].get("x-api-key")
    assert [e.call.name for e in events if isinstance(e, ToolCallReady)] == ["read"]


async def test_oauth_generic_429_explains_model_access() -> None:
    body = json.dumps({"type": "error", "error": {"type": "rate_limit_error", "message": "Error"}})
    recorder = Recorder(429, body)
    client = anthropic.AsyncAnthropic(
        auth_token="sk-ant-oat-test",
        api_key=None,
        max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(recorder)),
    )
    provider = AnthropicProvider(api_key="sk-ant-oat-test", client=client, oauth=True)
    with pytest.raises(ProviderError, match=r"Claude OAuth.*model access"):
        await drain(provider)


@pytest.mark.parametrize("model", ["claude-haiku-4-5", "claude-haiku-4-5-20251001"])
async def test_older_haiku_does_not_request_adaptive_thinking(model: str) -> None:
    recorder = Recorder(200, ANTHROPIC_TOOL_TURN)
    client = anthropic.AsyncAnthropic(
        auth_token="sk-ant-oat-test",
        api_key=None,
        max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(recorder)),
    )
    provider = AnthropicProvider(api_key="sk-ant-oat-test", model=model, client=client, oauth=True)
    await drain(provider)
    assert "thinking" not in recorder.payloads[0]


async def test_anthropic_fallbacks_only_for_supported_models() -> None:
    recorder = Recorder(200, ANTHROPIC_TOOL_TURN)
    await drain(anthropic_provider(recorder, model="claude-haiku-5-5"))
    assert "fallbacks" not in recorder.payloads[0]
    assert "anthropic-beta" not in recorder.headers[0]


async def test_anthropic_api_error_becomes_provider_error() -> None:
    body = json.dumps({"type": "error", "error": {"type": "overloaded_error", "message": "busy"}})
    provider = anthropic_provider(Recorder(529, body))
    with pytest.raises(ProviderError, match="anthropic 529"):
        await drain(provider)


async def test_anthropic_context_overflow_is_distinguished() -> None:
    body = json.dumps(
        {
            "type": "error",
            "error": {"type": "invalid_request_error", "message": "prompt is too long: 250000"},
        }
    )
    with pytest.raises(ContextOverflow):
        await drain(anthropic_provider(Recorder(400, body)))


def test_anthropic_replays_native_blocks_and_merges_tool_results() -> None:
    native = NativeContent(
        provider="anthropic",
        blocks=(
            {"type": "thinking", "thinking": "", "signature": "sig"},
            {"type": "tool_use", "id": "t1", "name": "ls", "input": {}},
            {"type": "tool_use", "id": "t2", "name": "ls", "input": {}},
        ),
    )
    history = [
        LlmMessage(role="user", content="hi"),
        LlmMessage(role="assistant", content="", native=native),
        LlmMessage(role="tool", content="a", tool_call_id="t1"),
        LlmMessage(role="tool", content="b", tool_call_id="t2", is_error=True),
        LlmMessage(role="user", content="also"),
    ]
    messages = plain(anthropic_messages(history))

    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[1]["content"] == list(native.blocks)
    assert [b["type"] for b in messages[2]["content"]] == ["tool_result", "tool_result", "text"]


def test_anthropic_ignores_foreign_native_blocks() -> None:
    native = NativeContent(provider="openai", blocks=({"type": "reasoning"},))
    call = ToolCallRequest(id="t1", name="ls", args={"path": "."})
    history = [
        LlmMessage(role="user", content="hi"),
        LlmMessage(role="assistant", content="ok", tool_calls=(call,), native=native),
    ]
    messages = plain(anthropic_messages(history))

    assert messages[1]["content"] == [
        {"type": "text", "text": "ok"},
        {"type": "tool_use", "id": "t1", "name": "ls", "input": {"path": "."}},
    ]


def chunk(delta: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
    return {
        "id": "c1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "qwen",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


OPENAI_TOOL_TURN = chunks(
    chunk({"role": "assistant", "reasoning_content": "think"}),
    chunk({"content": "Reading"}),
    chunk(
        {
            "tool_calls": [
                {
                    "index": 0,
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read", "arguments": '{"pa'},
                }
            ]
        }
    ),
    chunk({"tool_calls": [{"index": 0, "function": {"arguments": 'th": "a.txt"}'}}]}),
    chunk(
        {"tool_calls": [{"index": 1, "id": "call_2", "function": {"name": "ls", "arguments": "{"}}]}
    ),
    chunk({}, finish="tool_calls"),
    {
        "id": "c1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "qwen",
        "choices": [],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 7,
            "total_tokens": 107,
            "prompt_tokens_details": {"cached_tokens": 60},
        },
    },
)


async def test_openai_stream_normalizes_events() -> None:
    recorder = Recorder(200, OPENAI_TOOL_TURN)
    events = await drain(openai_provider(recorder))

    assert [e for e in events if isinstance(e, ThinkingDelta)] == [ThinkingDelta(text="think")]
    assert [e for e in events if isinstance(e, TextDelta)] == [TextDelta(text="Reading")]
    calls = [e.call for e in events if isinstance(e, ToolCallReady)]
    assert calls[0] == ToolCallRequest(id="call_1", name="read", args={"path": "a.txt"})
    assert calls[1].parse_error is not None
    usage = next(e.usage for e in events if isinstance(e, UsageReport))
    assert usage == Usage(input_tokens=40, output_tokens=7, cache_read_tokens=60)
    assert events[-1] == Stop(reason="tool_use")


async def test_openai_request_shape() -> None:
    recorder = Recorder(200, OPENAI_TOOL_TURN)
    await drain(openai_provider(recorder))
    payload = recorder.payloads[0]

    assert payload["model"] == "qwen"
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}
    assert payload["messages"][0] == {"role": "system", "content": "be careful"}
    assert payload["tools"][0]["function"]["name"] == "read"
    assert "reasoning_effort" not in payload
    assert "max_completion_tokens" not in payload


async def test_openai_api_error_becomes_provider_error() -> None:
    body = json.dumps({"error": {"message": "slow down", "type": "rate_limit"}})
    with pytest.raises(ProviderError, match="openai 429"):
        await drain(openai_provider(Recorder(429, body)))


async def test_openai_context_overflow_is_distinguished() -> None:
    body = json.dumps(
        {
            "error": {
                "message": "maximum context length exceeded",
                "type": "invalid_request_error",
                "code": "context_length_exceeded",
            }
        }
    )
    with pytest.raises(ContextOverflow):
        await drain(openai_provider(Recorder(400, body)))
    other = json.dumps({"error": {"message": "bad", "type": "invalid_request_error"}})
    with pytest.raises(ProviderError) as plain:
        await drain(openai_provider(Recorder(400, other)))
    assert not isinstance(plain.value, ContextOverflow)


def test_openai_messages_round_trip_tool_calls() -> None:
    call = ToolCallRequest(id="call_1", name="read", args={"path": "a.txt"})
    history = [
        LlmMessage(role="user", content="hi"),
        LlmMessage(role="assistant", content="", tool_calls=(call,)),
        LlmMessage(role="tool", content="alpha", tool_call_id="call_1"),
        LlmMessage(role="assistant", content=""),
    ]
    messages = plain(openai_messages("sys", history))

    assert [m["role"] for m in messages] == ["system", "user", "assistant", "tool"]
    assert messages[2] == {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "read", "arguments": '{"path": "a.txt"}'},
            }
        ],
    }


IMAGE = LlmImage(media_type="image/png", data="aW1n")


def test_anthropic_sends_images_before_the_prompt_text() -> None:
    messages = anthropic_messages((LlmMessage(role="user", content="look", images=(IMAGE,)),))
    assert messages == [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": "aW1n"},
                },
                {"type": "text", "text": "look"},
            ],
        }
    ]


def test_openai_sends_images_as_data_urls() -> None:
    messages = openai_messages("sys", (LlmMessage(role="user", content="look", images=(IMAGE,)),))
    assert messages[1] == {
        "role": "user",
        "content": [
            {"type": "text", "text": "look"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,aW1n"}},
        ],
    }
