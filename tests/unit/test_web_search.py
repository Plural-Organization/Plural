import json
from collections.abc import Sequence
from contextlib import nullcontext
from functools import partial
from pathlib import Path
from typing import Any

import anthropic
import httpx2
import openai
import pytest
from pydantic import SecretStr
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.native_tools import WebSearchTool as NativeWebSearch
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider

from plural.agent.providers.api.anthropic.oauth import AnthropicOAuthProvider
from plural.agent.providers.base import ProviderError
from plural.agent.providers.fake import FakeProvider
from plural.agent.providers.web_search import (
    PydanticWebSearch,
    anthropic_oauth_search,
    web_search_tool,
)
from plural.agent.tools.base import ToolError
from plural.agent.tools.extra.search import (
    Found,
    SearchFailed,
    Source,
    WebSearchSlot,
    WebSearchTool,
)
from plural.host.bootstrap import build_web_search
from plural.host.config import HostSettings

ANTHROPIC_REPLY: dict[str, Any] = {
    "id": "msg_1",
    "type": "message",
    "role": "assistant",
    "model": "claude-haiku-4-5",
    "content": [
        {
            "type": "server_tool_use",
            "id": "srvtoolu_1",
            "name": "web_search",
            "input": {"query": "plural agent"},
        },
        {
            "type": "web_search_tool_result",
            "tool_use_id": "srvtoolu_1",
            "content": [
                {
                    "type": "web_search_result",
                    "title": "Plural",
                    "url": "https://github.com/Plural-Organization/Plural",
                    "encrypted_content": "x",
                    "page_age": None,
                },
                {
                    "type": "web_search_result",
                    "title": "Plural again",
                    "url": "https://github.com/Plural-Organization/Plural",
                    "encrypted_content": "y",
                    "page_age": None,
                },
            ],
        },
        {"type": "text", "text": "Plural is a shared room for a coding agent."},
    ],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 10, "output_tokens": 20},
}

OPENAI_REPLY: dict[str, Any] = {
    "id": "resp_1",
    "object": "response",
    "created_at": 1,
    "model": "gpt-5",
    "status": "completed",
    "output": [
        {
            "type": "web_search_call",
            "id": "ws_1",
            "status": "completed",
            "action": {
                "type": "search",
                "query": "plural agent",
                "sources": [{"type": "url", "url": "https://pypi.org/project/plural-agent/"}],
            },
        },
        {
            "type": "message",
            "id": "msg_1",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": "It is on PyPI.", "annotations": []}],
        },
    ],
    "parallel_tool_calls": True,
    "tool_choice": "auto",
    "tools": [],
    "usage": {
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens_details": {"reasoning_tokens": 0},
    },
}


def anthropic_stream(message: dict[str, Any]) -> str:
    """The server-sent events Anthropic streams for `message`, one whole block per event."""
    start: dict[str, Any] = {**message, "content": [], "stop_reason": None}
    events: list[dict[str, Any]] = [{"type": "message_start", "message": start}]
    for index, block in enumerate(message["content"]):
        events.append({"type": "content_block_start", "index": index, "content_block": block})
        events.append({"type": "content_block_stop", "index": index})
    events.append(
        {
            "type": "message_delta",
            "delta": {"stop_reason": message["stop_reason"], "stop_sequence": None},
            "usage": message["usage"],
        }
    )
    events.append({"type": "message_stop"})
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)


class Recorder:
    def __init__(self, reply: dict[str, Any], status: int = 200) -> None:
        self.reply = reply
        self.status = status
        self.payloads: list[dict[str, Any]] = []
        self.headers: list[httpx2.Headers] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        payload = json.loads(request.content)
        self.payloads.append(payload)
        self.headers.append(request.headers)
        if payload.get("stream") and self.status == 200 and self.reply.get("type") == "message":
            return httpx2.Response(
                200,
                text=anthropic_stream(self.reply),
                headers={"content-type": "text/event-stream"},
            )
        return httpx2.Response(self.status, json=self.reply)


def anthropic_search(recorder: Recorder, tool: NativeWebSearch) -> PydanticWebSearch:
    client = anthropic.AsyncAnthropic(
        api_key="test",
        max_retries=0,
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(recorder)),
    )
    model = AnthropicModel("claude-haiku-4-5", provider=AnthropicProvider(anthropic_client=client))
    return PydanticWebSearch("anthropic:claude-haiku-4-5", partial(nullcontext, model), tool)


async def test_anthropic_searches_with_the_native_tool_and_its_settings() -> None:
    recorder = Recorder(ANTHROPIC_REPLY)
    tool = NativeWebSearch(max_uses=3, user_location={"country": "KZ", "city": "Almaty"})
    found = await anthropic_search(recorder, tool).search(
        "plural agent", allowed_domains=["github.com"]
    )

    assert found == Found(
        answer="Plural is a shared room for a coding agent.",
        sources=(Source("Plural", "https://github.com/Plural-Organization/Plural"),),
    )
    [native] = [t for t in recorder.payloads[0]["tools"] if t["name"] == "web_search"]
    assert native["type"].startswith("web_search_")
    assert native["max_uses"] == 3
    assert native["allowed_domains"] == ["github.com"]
    assert native["user_location"]["country"] == "KZ"
    assert native["user_location"]["city"] == "Almaty"
    assert "plural agent" in json.dumps(recorder.payloads[0]["messages"])


async def test_openai_searches_with_the_responses_api_native_tool() -> None:
    recorder = Recorder(OPENAI_REPLY)
    client = openai.AsyncOpenAI(
        api_key="test",
        max_retries=0,
        http_client=openai.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(recorder)),
    )
    model = OpenAIResponsesModel("gpt-5", provider=OpenAIProvider(openai_client=client))
    settings = OpenAIResponsesModelSettings(openai_include_web_search_sources=True)
    search = PydanticWebSearch(
        "openai:gpt-5", partial(nullcontext, model), NativeWebSearch(), settings
    )
    found = await search.search("plural agent")

    assert found.answer == "It is on PyPI."
    assert [tool["type"] for tool in recorder.payloads[0]["tools"]] == ["web_search"]
    assert "web_search_call.action.sources" in recorder.payloads[0]["include"]
    assert found.sources == (
        Source("https://pypi.org/project/plural-agent/", "https://pypi.org/project/plural-agent/"),
    )


async def test_a_provider_error_becomes_a_search_failure() -> None:
    recorder = Recorder({"type": "error", "error": {"type": "api_error", "message": "boom"}}, 500)
    with pytest.raises(SearchFailed):
        await anthropic_search(recorder, NativeWebSearch()).search("q")


class FakeSearcher:
    model = "anthropic:claude-haiku-4-5"

    def __init__(self, found: Found | Exception) -> None:
        self.found = found
        self.asked: list[tuple[str, Sequence[str], Sequence[str]]] = []

    async def search(
        self,
        query: str,
        *,
        allowed_domains: Sequence[str] = (),
        blocked_domains: Sequence[str] = (),
    ) -> Found:
        self.asked.append((query, allowed_domains, blocked_domains))
        if isinstance(self.found, Exception):
            raise self.found
        return self.found


async def test_the_tool_returns_the_answer_with_numbered_sources() -> None:
    searcher = FakeSearcher(Found("An answer.", (Source("One", "https://one.example"),)))
    prepared = WebSearchTool(searcher).prepare({"query": "q", "blocked_domains": ["spam.example"]})
    result = await prepared.execute(None)  # pyright: ignore[reportArgumentType]

    assert result.content == "An answer.\n\nSources:\n1. One\n   https://one.example"
    assert searcher.asked == [("q", [], ["spam.example"])]
    assert (prepared.subject, prepared.risk.value) == ("q", "read")


async def test_the_tool_reports_failures_and_conflicting_domains() -> None:
    failing = WebSearchTool(FakeSearcher(SearchFailed("rate limited")))
    with pytest.raises(ToolError, match="anthropic:claude-haiku-4-5 failed: rate limited"):
        await failing.prepare({"query": "q"}).execute(None)  # pyright: ignore[reportArgumentType]
    both = {"query": "q", "allowed_domains": ["a.example"], "blocked_domains": ["b.example"]}
    with pytest.raises(ToolError, match="not both"):
        await failing.prepare(both).execute(None)  # pyright: ignore[reportArgumentType]


async def test_a_claude_login_searches_with_a_fresh_token_and_the_oauth_beta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = Recorder(ANTHROPIC_REPLY)
    tokens = iter(["sk-ant-oat-1", "sk-ant-oat-2"])

    async def token() -> str:
        return next(tokens)

    real = anthropic.AsyncAnthropic

    def routed(**kwargs: Any) -> anthropic.AsyncAnthropic:
        transport = httpx2.MockTransport(recorder)
        return real(**kwargs, http_client=anthropic.DefaultAsyncHttpxClient(transport=transport))

    monkeypatch.setattr("anthropic.AsyncAnthropic", routed)
    search = anthropic_oauth_search("claude-haiku-4-5", token, NativeWebSearch())
    await search.search("first")
    await search.search("second")

    assert [h["authorization"] for h in recorder.headers] == [
        "Bearer sk-ant-oat-1",
        "Bearer sk-ant-oat-2",
    ]
    assert all("oauth-2025-04-20" in h["anthropic-beta"] for h in recorder.headers)


def test_the_host_searches_only_with_a_provider_that_can(tmp_path: Path) -> None:
    key, fake = SecretStr("sk-test"), FakeProvider()
    found = build_web_search(HostSettings(provider="anthropic", api_key=key), "sk-test", fake)
    assert found is not None
    assert found.model == "anthropic:claude-opus-5-5"
    openai_settings = HostSettings(provider="openai", model="gpt-5", api_key=key)
    assert build_web_search(openai_settings, "sk-test", fake) is not None
    cheap = HostSettings(provider="anthropic", web_search_model="anthropic:claude-haiku-4-5")
    assert build_web_search(cheap, "sk-test", fake).model == "anthropic:claude-haiku-4-5"  # pyright: ignore[reportOptionalMemberAccess]
    other = HostSettings(provider="openai", model="gpt-5", web_search_model="anthropic:claude-x")
    assert build_web_search(other, "sk-test", fake).model == "openai:gpt-5"  # pyright: ignore[reportOptionalMemberAccess]

    (tmp_path / "oauth.json").write_text(
        json.dumps({"access": "a", "refresh": "r", "expires": 9e12})
    )
    login = AnthropicOAuthProvider(
        credentials_path=tmp_path / "oauth.json",
        model="claude-haiku-4-5",
        max_tokens=1,
        effort=None,
    )
    oauth = HostSettings(provider="anthropic_oauth", model="claude-haiku-4-5")
    assert build_web_search(oauth, None, login) is not None

    assert build_web_search(HostSettings(provider="anthropic"), None, fake) is None
    assert build_web_search(HostSettings(provider="claude_code"), "sk-test", fake) is None
    off = HostSettings(provider="anthropic", web_search=False)
    assert build_web_search(off, "sk-test", fake) is None
    local = HostSettings(provider="openai", model="qwen", base_url="http://localhost:11434/v1")
    assert build_web_search(local, "sk-test", fake) is None


def test_the_slot_offers_web_search_only_while_there_is_a_search() -> None:
    slot = WebSearchSlot()
    assert list(slot.tools()) == []
    slot.use(FakeSearcher(Found("a", ())))
    assert [tool.name for tool in slot.tools()] == ["web_search"]
    slot.use(None)
    assert list(slot.tools()) == []


def test_the_settings_become_web_search_tool_fields() -> None:
    tool = web_search_tool(
        context_size="high",
        max_uses=2,
        blocked_domains=["spam.example"],
        location={"country": "KZ", "city": ""},
    )
    assert tool == NativeWebSearch(
        search_context_size="high",
        max_uses=2,
        blocked_domains=["spam.example"],
        user_location={"country": "KZ"},
    )


async def test_an_expired_claude_login_is_a_search_failure() -> None:
    async def expired() -> str:
        raise ProviderError("Claude login expired; sign in again in Model settings")

    search = anthropic_oauth_search("claude-haiku-4-5", expired, NativeWebSearch())
    with pytest.raises(SearchFailed, match="login expired"):
        await search.search("q")
