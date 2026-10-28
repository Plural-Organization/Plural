from collections.abc import Iterable
from typing import Protocol

from plural.agent.providers.base import ToolCallRequest, ToolSchema
from plural.agent.tools.base import PreparedCall, Tool
from plural.agent.tools.bash import BashTool
from plural.agent.tools.edit import EditTool, MultiEditTool
from plural.agent.tools.glob import GlobTool
from plural.agent.tools.grep import GrepTool
from plural.agent.tools.ls import LsTool
from plural.agent.tools.read import ReadTool
from plural.agent.tools.web import WebFetchTool
from plural.agent.tools.write import WriteTool


class UnknownTool(LookupError):
    pass


class ToolSource(Protocol):
    def tools(self) -> Iterable[Tool]: ...


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._sources: list[ToolSource] = []
        self._allowed: frozenset[str] | None = None

    def subset(self, names: Iterable[str]) -> "ToolRegistry":
        """A view with only these tools, which still follows tools registered or connected later."""
        view = ToolRegistry()
        view._tools = self._tools
        view._sources = self._sources
        view._allowed = frozenset(names)
        return view

    def _visible(self, name: str) -> bool:
        return (
            self._allowed is None
            or name in self._allowed
            or ("mcp" in self._allowed and name.startswith("mcp__"))
        )

    def add_source(self, source: ToolSource) -> None:
        self._sources.append(source)

    def _dynamic(self) -> dict[str, Tool]:
        return {
            tool.name: tool
            for source in self._sources
            for tool in source.tools()
            if tool.name not in self._tools
        }

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name} is already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        tool = self._tools.get(name) or self._dynamic().get(name)
        if tool is None or not self._visible(name):
            raise UnknownTool(f"unknown tool {name}")
        return tool

    def schemas(self) -> tuple[ToolSchema, ...]:
        tools = (*self._tools.values(), *self._dynamic().values())
        return tuple(tool.schema() for tool in tools if self._visible(tool.name))

    def prepare(self, call: ToolCallRequest) -> PreparedCall:
        return self.get(call.name).prepare(call.args)


def builtin_tools() -> ToolRegistry:
    registry = ToolRegistry()
    for tool in (
        ReadTool(),
        WriteTool(),
        EditTool(),
        MultiEditTool(),
        BashTool(),
        GrepTool(),
        GlobTool(),
        LsTool(),
        WebFetchTool(),
    ):
        registry.register(tool)
    return registry
