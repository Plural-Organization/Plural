from collections.abc import Mapping
from pathlib import Path

import pytest
from pydantic import JsonValue

from plural.agent.providers.base import ToolCallRequest, ToolSchema
from plural.agent.sandbox.base import Workspace
from plural.agent.sandbox.local import LocalBackend
from plural.agent.tools.base import PreparedCall, Tool, ToolCtx, ToolResult
from plural.agent.tools.discovery import ToolSearchTool, rank, tokenize
from plural.agent.tools.registry import Exposure, ToolRegistry, UnknownTool, builtin_tools
from plural.protocol.models import ToolRisk


class Fake:
    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self._description = description

    def schema(self) -> ToolSchema:
        return ToolSchema(name=self.name, description=self._description, parameters={})

    def prepare(self, raw: Mapping[str, JsonValue]) -> PreparedCall:
        async def run(ctx: ToolCtx) -> ToolResult:
            return ToolResult("ok")

        return PreparedCall(name=self.name, risk=ToolRisk.READ, subject="", execute=run)


class Server:
    def __init__(self, *tools: Tool) -> None:
        self.items = list(tools)

    def tools(self) -> list[Tool]:
        return self.items


def names(registry: ToolRegistry) -> list[str]:
    return [schema.name for schema in registry.schemas()]


def test_only_core_tools_are_declared() -> None:
    assert names(builtin_tools()) == ["read", "grep", "glob", "ls", "edit", "write", "bash"]
    assert [entry.tool.name for entry in builtin_tools().deferred()] == ["multi_edit", "web_fetch"]


def test_loading_and_pinning_declare_deferred_tools() -> None:
    registry = ToolRegistry()
    registry.register(Fake("read", "Read a file"))
    registry.add_source(
        Server(Fake("mcp__browser__click", "Click"), Fake("mcp__browser__navigate", "Go")),
        exposure=Exposure.DEFERRED,
    )
    registry.register(Fake("board_draw", "Draw"), exposure=Exposure.DEFERRED)
    assert names(registry) == ["read"]

    revision = registry.revision
    assert registry.load(["board_draw", "read", "board_draw"]) == ("board_draw",)
    assert registry.revision == revision + 1
    assert registry.load(["board_draw"]) == ()
    assert names(registry) == ["read", "board_draw"]

    registry.pin(["browser"])
    assert names(registry) == [
        "read",
        "board_draw",
        "mcp__browser__click",
        "mcp__browser__navigate",
    ]


def test_calling_a_deferred_tool_by_name_loads_it() -> None:
    registry = builtin_tools()
    registry.prepare(ToolCallRequest(id="c1", name="web_fetch", args={"url": "https://a.b"}))
    assert "web_fetch" in names(registry)
    with pytest.raises(UnknownTool):
        registry.prepare(ToolCallRequest(id="c2", name="nope", args={}))


def test_a_subset_declares_every_tool_it_allows() -> None:
    assert [s.name for s in builtin_tools().subset(["read", "web_fetch"]).schemas()] == [
        "read",
        "web_fetch",
    ]


def test_bm25_ranks_by_words_and_puts_an_exact_name_first() -> None:
    assert tokenize("searchIssues and the pages") == ["search", "issue", "page"]
    documents = [
        ("mcp__browser__navigate", "navigate go to a url in the browser page"),
        ("mcp__browser__click", "click an element on the web page button"),
        ("board_draw", "draw shapes on the shared board"),
    ]
    assert rank("click a button on the page", documents, 2) == [
        "mcp__browser__click",
        "mcp__browser__navigate",
    ]
    assert rank("navigate", documents, 1) == ["mcp__browser__navigate"]
    assert rank("board_draw", documents, 5)[0] == "board_draw"
    assert rank("the and of", documents, 5) == []


async def test_tool_search_lists_groups_and_loads_matches(tmp_path: Path) -> None:
    registry = ToolRegistry()
    registry.add_source(
        Server(Fake("mcp__browser__click", "Click an element on the page")),
        exposure=Exposure.DEFERRED,
    )
    registry.register(Fake("board_draw", "Draw on the shared board"), exposure=Exposure.DEFERRED)
    search = ToolSearchTool(registry)
    registry.register(search)
    assert "board (1), browser (1)" in search.schema().description

    ctx = ToolCtx(workspace=Workspace.at(tmp_path), backend=LocalBackend())
    prepared = search.prepare({"query": "click the page"})
    result = await prepared.execute(ctx)
    assert "mcp__browser__click: Click an element on the page" in result.content
    assert "mcp__browser__click" in names(registry)
    assert "board_draw" not in names(registry)
    assert "browser" not in search.schema().description
