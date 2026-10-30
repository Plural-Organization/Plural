from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from pydantic import Field

from plural.agent.tools.base import ToolArgs, ToolCtx, ToolError, ToolResult, ToolSpec, TypedTool
from plural.protocol.models import ToolRisk


class SearchFailed(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Source:
    title: str
    url: str


@dataclass(frozen=True, slots=True)
class Found:
    answer: str
    sources: tuple[Source, ...]


class Searcher(Protocol):
    @property
    def model(self) -> str: ...

    async def search(
        self,
        query: str,
        *,
        allowed_domains: Sequence[str] = (),
        blocked_domains: Sequence[str] = (),
    ) -> Found: ...


class WebSearchArgs(ToolArgs):
    query: str = Field(min_length=1, max_length=500, description="What to search for.")
    allowed_domains: list[str] = Field(
        default_factory=list[str],
        description="Search only these domains, such as docs.python.org. Leave empty for all.",
    )
    blocked_domains: list[str] = Field(
        default_factory=list[str],
        description="Never return results from these domains.",
    )


class WebSearchTool(TypedTool[WebSearchArgs]):
    spec = ToolSpec(
        name="web_search",
        description=(
            "Search the web with the model provider's own search engine. Returns a short answer "
            "and the pages it came from; web_fetch a page for its full text."
        ),
        risk=ToolRisk.READ,
        args_model=WebSearchArgs,
    )

    def __init__(self, searcher: Searcher) -> None:
        self._searcher = searcher

    def subject(self, args: WebSearchArgs) -> str:
        return args.query

    async def run(self, args: WebSearchArgs, ctx: ToolCtx) -> ToolResult:
        if args.allowed_domains and args.blocked_domains:
            raise ToolError("give allowed_domains or blocked_domains, not both")
        try:
            found = await self._searcher.search(
                args.query,
                allowed_domains=args.allowed_domains,
                blocked_domains=args.blocked_domains,
            )
        except SearchFailed as error:
            raise ToolError(f"search with {self._searcher.model} failed: {error}") from None
        lines = [found.answer.strip() or "(no answer)"]
        if found.sources:
            lines.append("\nSources:")
            lines.extend(
                f"{index}. {source.title}\n   {source.url}"
                for index, source in enumerate(found.sources, 1)
            )
        else:
            lines.append("\nThe search returned no sources.")
        return ToolResult("\n".join(lines))


class WebSearchSlot:
    """Offers `web_search` while the session's provider can search, and nothing otherwise."""

    def __init__(self) -> None:
        self._tool: WebSearchTool | None = None

    def use(self, searcher: Searcher | None) -> None:
        self._tool = WebSearchTool(searcher) if searcher is not None else None

    def tools(self) -> Iterable[WebSearchTool]:
        return (self._tool,) if self._tool is not None else ()
