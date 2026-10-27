from plural.agent.providers.base import ToolCallRequest, ToolSchema
from plural.agent.tools.base import PreparedCall, Tool
from plural.agent.tools.bash import BashTool
from plural.agent.tools.edit import EditTool, MultiEditTool
from plural.agent.tools.glob import GlobTool
from plural.agent.tools.grep import GrepTool
from plural.agent.tools.ls import LsTool
from plural.agent.tools.read import ReadTool
from plural.agent.tools.web import WebFetchTool, WebSearchTool
from plural.agent.tools.write import WriteTool


class UnknownTool(LookupError):
    pass


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name} is already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise UnknownTool(f"unknown tool {name}") from None

    def schemas(self) -> tuple[ToolSchema, ...]:
        return tuple(tool.schema() for tool in self._tools.values())

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
        WebSearchTool(),
        WebFetchTool(),
    ):
        registry.register(tool)
    return registry
