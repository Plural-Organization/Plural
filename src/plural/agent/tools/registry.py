from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
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


class Exposure(StrEnum):
    """How the model reaches a tool."""

    CORE = "core"  # declared on every request
    DEFERRED = "deferred"  # found with tool_search, or called by its exact name, then declared


class ToolSource(Protocol):
    def tools(self) -> Iterable[Tool]: ...


@dataclass(frozen=True, slots=True)
class Entry:
    tool: Tool
    exposure: Exposure

    @property
    def group(self) -> str:
        return group_of(self.tool.name)


def group_of(name: str) -> str:
    """The family a tool belongs to: its MCP server, or the word its name starts with."""
    if name.startswith("mcp__"):
        return name.split("__")[1]
    return name.split("_")[0]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Entry] = {}
        self._sources: list[tuple[ToolSource, Exposure]] = []
        self._allowed: frozenset[str] | None = None
        self._loaded: set[str] = set()
        self._pinned: frozenset[str] = frozenset()
        self._revision = 0

    def subset(self, names: Iterable[str]) -> "ToolRegistry":
        """A view with only these tools, all declared, that follows tools registered later."""
        view = ToolRegistry()
        view._tools = self._tools
        view._sources = self._sources
        view._allowed = frozenset(names)
        return view

    def register(self, tool: Tool, *, exposure: Exposure = Exposure.CORE) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name} is already registered")
        self._tools[tool.name] = Entry(tool, exposure)

    def add_source(self, source: ToolSource, *, exposure: Exposure = Exposure.CORE) -> None:
        self._sources.append((source, exposure))

    def pin(self, names: Iterable[str]) -> None:
        """Declare these tools, or every tool of these groups, as if they were core."""
        self._pinned = frozenset(names)

    @property
    def revision(self) -> int:
        """Grows each time a deferred tool is loaded, so a run knows to declare it."""
        return self._revision

    @property
    def loaded(self) -> frozenset[str]:
        return frozenset(self._loaded)

    def load(self, names: Iterable[str]) -> tuple[str, ...]:
        """Declare deferred tools from now on and return the ones that were not declared yet."""
        entries = self._entries()
        fresh = tuple(
            name
            for name in dict.fromkeys(names)
            if name not in self._loaded and not (name in entries and self._declared(entries[name]))
        )
        if fresh:
            self._loaded.update(fresh)
            self._revision += 1
        return fresh

    def get(self, name: str) -> Tool:
        entry = self._entries().get(name)
        if entry is None or not self._allowed_name(name):
            raise UnknownTool(f"unknown tool {name}")
        return entry.tool

    def schemas(self) -> tuple[ToolSchema, ...]:
        return tuple(
            entry.tool.schema()
            for entry in self._entries().values()
            if self._allowed_name(entry.tool.name) and self._declared(entry)
        )

    def deferred(self) -> tuple[Entry, ...]:
        """Tools the model does not see yet: what tool_search searches."""
        return tuple(
            entry
            for entry in self._entries().values()
            if self._allowed_name(entry.tool.name) and not self._declared(entry)
        )

    def prepare(self, call: ToolCallRequest) -> PreparedCall:
        tool = self.get(call.name)
        # Calling a deferred tool by its exact name loads it: the gate still decides the call.
        self.load((call.name,))
        return tool.prepare(call.args)

    def _entries(self) -> dict[str, Entry]:
        dynamic = {
            tool.name: Entry(tool, exposure)
            for source, exposure in self._sources
            for tool in source.tools()
            if tool.name not in self._tools
        }
        return {**self._tools, **dynamic}

    def _allowed_name(self, name: str) -> bool:
        return (
            self._allowed is None
            or name in self._allowed
            or ("mcp" in self._allowed and name.startswith("mcp__"))
        )

    def _declared(self, entry: Entry) -> bool:
        name = entry.tool.name
        return (
            self._allowed is not None
            or entry.exposure is Exposure.CORE
            or name in self._loaded
            or name in self._pinned
            or entry.group in self._pinned
        )


def builtin_tools() -> ToolRegistry:
    registry = ToolRegistry()
    for tool in (ReadTool(), GrepTool(), GlobTool(), LsTool(), EditTool(), WriteTool(), BashTool()):
        registry.register(tool)
    for tool in (MultiEditTool(), WebFetchTool()):
        registry.register(tool, exposure=Exposure.DEFERRED)
    return registry
