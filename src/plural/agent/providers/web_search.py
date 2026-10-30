"""Web search through Pydantic AI's `WebSearchTool`, run by the model provider's search engine.

The search is a short Pydantic AI agent run with the native tool attached: the provider searches on
its own side and the model answers from what it found. Plural's `web_search` tool calls it, so a
search still waits for the host's approval and shows in the room like any other tool call.
"""

import os
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager, nullcontext
from dataclasses import replace
from functools import partial
from typing import Final, Literal, cast

from anthropic import AsyncAnthropic
from pydantic_ai import Agent, NativeToolReturnPart
from pydantic_ai.capabilities import NativeTool
from pydantic_ai.exceptions import AgentRunError, UserError
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.native_tools import WebSearchTool, WebSearchUserLocation
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

from plural.agent.providers.api.anthropic.adapter import OAUTH_BETA
from plural.agent.providers.base import ProviderError
from plural.agent.tools.extra.search import Found, SearchFailed, Source

INSTRUCTIONS: Final = (
    "You are a web search step inside a coding agent. Always run a web search for the query "
    "first; never answer from memory and never ask a question back. Then summarise what the "
    "results say about it, quoting names, numbers and dates exactly. Say plainly when the "
    "results do not answer it. Keep the answer short."
)

# Pydantic AI greets on stdout, which the host's --json mode uses for its own protocol.
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

ModelFactory = Callable[[], AbstractAsyncContextManager[Model]]


class PydanticWebSearch:
    def __init__(
        self,
        label: str,
        model: ModelFactory,
        tool: WebSearchTool,
        settings: ModelSettings | None = None,
    ) -> None:
        self._label = label
        self._model = model
        self._tool = tool
        self._settings = settings

    @property
    def model(self) -> str:
        return self._label

    async def search(
        self,
        query: str,
        *,
        allowed_domains: Sequence[str] = (),
        blocked_domains: Sequence[str] = (),
    ) -> Found:
        tool = replace(
            self._tool,
            allowed_domains=list(allowed_domains) or self._tool.allowed_domains,
            blocked_domains=list(blocked_domains) or self._tool.blocked_domains,
        )
        try:
            async with self._model() as model:
                agent = Agent(
                    model,
                    instructions=INSTRUCTIONS,
                    model_settings=self._settings,
                    capabilities=[NativeTool(tool)],
                )
                result = await agent.run(f"Search the web for: {query}")
        except (AgentRunError, UserError, ProviderError, OSError) as error:
            raise SearchFailed(str(error)) from error
        sources: dict[str, Source] = {}
        for message in result.all_messages():
            for part in message.parts:
                if isinstance(part, NativeToolReturnPart) and part.tool_name == tool.kind:
                    for source in _sources(part.content):
                        sources.setdefault(source.url, source)
        return Found(answer=result.output, sources=tuple(sources.values()))


def web_search_tool(
    *,
    context_size: Literal["low", "medium", "high"] = "medium",
    max_uses: int | None = None,
    allowed_domains: Sequence[str] = (),
    blocked_domains: Sequence[str] = (),
    location: Mapping[str, str] | None = None,
) -> WebSearchTool:
    place = WebSearchUserLocation()
    for field in ("city", "region", "country", "timezone"):
        if location and (value := location.get(field)):
            place[field] = value
    return WebSearchTool(
        search_context_size=context_size,
        max_uses=max_uses,
        allowed_domains=list(allowed_domains) or None,
        blocked_domains=list(blocked_domains) or None,
        user_location=place or None,
    )


def anthropic_search(model: str, api_key: str, tool: WebSearchTool) -> PydanticWebSearch:
    found = AnthropicModel(model, provider=AnthropicProvider(api_key=api_key))
    return PydanticWebSearch(f"anthropic:{model}", partial(nullcontext, found), tool)


def anthropic_oauth_search(
    model: str, token: Callable[[], Awaitable[str]], tool: WebSearchTool
) -> PydanticWebSearch:
    """Search with a Claude login: each search asks for a fresh access token."""

    @asynccontextmanager
    async def signed_in() -> AsyncGenerator[Model]:
        client = AsyncAnthropic(api_key=None, auth_token=await token(), max_retries=0)
        try:
            yield AnthropicModel(model, provider=AnthropicProvider(anthropic_client=client))
        finally:
            await client.close()

    settings = AnthropicModelSettings(anthropic_betas=[OAUTH_BETA])
    return PydanticWebSearch(f"anthropic:{model}", signed_in, tool, settings)


def openai_search(model: str, api_key: str, tool: WebSearchTool) -> PydanticWebSearch:
    found = OpenAIResponsesModel(model, provider=OpenAIProvider(api_key=api_key))
    # Without it the Responses API leaves the pages out of its search calls.
    settings = OpenAIResponsesModelSettings(openai_include_web_search_sources=True)
    return PydanticWebSearch(f"openai:{model}", partial(nullcontext, found), tool, settings)


def _sources(content: object) -> Iterator[Source]:
    """Every titled URL in a native search result, whatever shape its provider gives it."""
    if isinstance(content, dict):
        fields = cast("dict[str, object]", content)
        url, title = fields.get("url"), fields.get("title")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            yield Source(title=title if isinstance(title, str) else url, url=url)
        for value in fields.values():
            yield from _sources(value)
    elif isinstance(content, list):
        for item in cast("list[object]", content):
            yield from _sources(item)
