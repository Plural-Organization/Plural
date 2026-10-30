import asyncio
import importlib.util
import inspect
import json
import keyword
import re
import sys
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from types import ModuleType
from typing import Final

import structlog
from pydantic import JsonValue

from plural.agent.providers.base import ToolSchema
from plural.agent.tools.base import PreparedCall, Tool, ToolCtx, ToolResult
from plural.agent.tools.registry import Exposure
from plural.host.inbox import Inbox, PluginPrompt, PluginReply
from plural.protocol.models import (
    PluginCommandView,
    PluginStatus,
    PluginView,
    Role,
    ToolRisk,
)

log = structlog.get_logger(__name__)

NAME: Final = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
BUILT_IN: Final = frozenset(
    {
        "abort",
        "cancel",
        "compact",
        "copy",
        "help",
        "invite",
        "leave",
        "mcp",
        "mode",
        "plugins",
        "policy",
        "quit",
        "settings",
        "skills",
        "who",
    }
)
TOOL_NAME: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
RISKS: Final = {"read": ToolRisk.READ, "write": ToolRisk.WRITE, "exec": ToolRisk.EXEC}
RUN_TIMEOUT_S: Final = 120.0
MAX_OUTPUT_CHARS: Final = 64_000

TEMPLATE: Final = '''\
"""Plural plugin /{name}. Edit it, then run /plugins reload.

Plugins run inside the host with the host's permissions. See docs/plugins.md.
"""


def setup(plural):
    @plural.command("{name}", description="Describe what /{name} does")
    async def {function}(ctx):
        # ctx.args is the text after the command, ctx.author is who ran it.
        await ctx.reply(f"Hello {{ctx.author}}! You wrote: {{ctx.args or 'nothing'}}")
        # To hand work to the agent as the person who ran the command:
        # await ctx.prompt(f"Explain {{ctx.args}}")

    # A tool the agent can call. It finds it with tool_search; the host approves each call
    # unless a policy rule allows it.
    # @plural.tool(
    #     "{function}_lookup",
    #     description="What the tool does",
    #     parameters={{"query": "What to look up"}},
    # )
    # async def lookup(args, ctx):
    #     return f"result for {{args['query']}}"
'''


class PluginError(Exception):
    pass


class CommandContext:
    def __init__(
        self,
        *,
        command: str,
        args: str,
        author: str,
        author_id: str,
        role: Role,
        workspace: Path,
        inbox: Inbox,
    ) -> None:
        self.command = command
        self.args = args
        self.author = author
        self.author_id = author_id
        self.role = role
        self.workspace = workspace
        self._inbox = inbox

    async def reply(self, text: str) -> None:
        self._inbox.put(PluginReply(self.command, self.author_id, text))

    async def prompt(self, text: str, *, follow_up: bool = False) -> None:
        self._inbox.put(PluginPrompt(self.command, self.author_id, text, follow_up=follow_up))

    async def run(self, *argv: str, timeout_s: float = RUN_TIMEOUT_S) -> str:
        return await _run_program(argv, self.workspace, timeout_s)


class ToolContext:
    """What a plugin tool gets besides its arguments. Its return value goes to the model."""

    def __init__(self, *, tool: str, workspace: Path, emit: Callable[[str], None]) -> None:
        self.tool = tool
        self.workspace = workspace
        self._emit = emit

    def log(self, text: str) -> None:
        """Stream progress to the room while the tool runs, like a command's live output."""
        self._emit(text if text.endswith("\n") else f"{text}\n")

    async def run(self, *argv: str, timeout_s: float = RUN_TIMEOUT_S) -> str:
        return await _run_program(argv, self.workspace, timeout_s)


async def _run_program(argv: tuple[str, ...], workspace: Path, timeout_s: float) -> str:
    if not argv:
        raise PluginError("run() needs a program to start")
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=workspace,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout_s)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise PluginError(f"{argv[0]} did not finish in {timeout_s:g}s") from None
    output = stdout.decode(errors="replace")[:MAX_OUTPUT_CHARS]
    if process.returncode != 0:
        detail = stderr.decode(errors="replace").strip()[:2000] or output.strip()[:2000]
        raise PluginError(f"{argv[0]} exited with {process.returncode}: {detail}")
    return output


Handler = Callable[[CommandContext], Awaitable[None]]
ToolHandler = Callable[[dict[str, JsonValue], ToolContext], Awaitable[object]]


class PluginTool:
    """A plugin function the agent calls like any tool. The gate decides each call by its risk."""

    def __init__(
        self,
        *,
        name: str,
        plugin: str,
        description: str,
        parameters: dict[str, JsonValue],
        risk: ToolRisk,
        exposure: Exposure,
        handler: ToolHandler,
        workspace: Path,
    ) -> None:
        self.name = name
        self.plugin = plugin
        self.risk = risk
        self.exposure = exposure
        self._description = description
        self._parameters = parameters
        self._handler = handler
        self._workspace = workspace

    def schema(self) -> ToolSchema:
        description = f"[{self.plugin} plugin] {self._description or self.name}"
        return ToolSchema(name=self.name, description=description, parameters=self._parameters)

    def prepare(self, raw: Mapping[str, JsonValue]) -> PreparedCall:
        args = dict(raw)
        return PreparedCall(
            name=self.name,
            risk=self.risk,
            subject=json.dumps(args, ensure_ascii=False, sort_keys=True)[:500],
            execute=lambda ctx: self._call(args, ctx),
        )

    async def _call(self, args: dict[str, JsonValue], ctx: ToolCtx) -> ToolResult:
        required = self._parameters.get("required")
        missing = [key for key in required if key not in args] if isinstance(required, list) else []
        if missing:
            return ToolResult(f"missing arguments: {', '.join(map(str, missing))}", is_error=True)
        context = ToolContext(tool=self.name, workspace=self._workspace, emit=ctx.emit)
        try:
            output = await self._handler(args, context)
        except Exception as error:
            # Plugin code is not ours: any failure becomes a result the model can read.
            log.warning("plugins.tool_failed", tool=self.name, error=str(error))
            return ToolResult(f"{self.name} failed: {_describe(error)}", is_error=True)
        text = (
            output
            if isinstance(output, str)
            else json.dumps(output, ensure_ascii=False, default=str)
        )
        return ToolResult(text[:MAX_OUTPUT_CHARS])


class PluginToolSource:
    """The loaded plugin tools of one exposure, as a registry source."""

    def __init__(self, host: "PluginHost", exposure: Exposure) -> None:
        self._host = host
        self._exposure = exposure

    def tools(self) -> Iterable[Tool]:
        return [tool for tool in self._host.tools() if tool.exposure is self._exposure]


def _parameters(spec: Mapping[str, JsonValue] | None) -> dict[str, JsonValue]:
    if spec is None:
        return {"type": "object", "properties": {}}
    if spec.get("type") == "object":
        return dict(spec)
    if not all(isinstance(value, str) for value in spec.values()):
        raise PluginError("parameters is a JSON schema object or a mapping of name to description")
    properties: dict[str, JsonValue] = {
        name: {"type": "string", "description": value} for name, value in spec.items()
    }
    return {"type": "object", "properties": properties, "required": list(spec)}


@dataclass(frozen=True, slots=True)
class PluginCommand:
    view: PluginCommandView
    handler: Handler


class PluginApi:
    def __init__(self, plugin: str, *, workspace: Path) -> None:
        self._plugin = plugin
        self._workspace = workspace
        self.commands: list[PluginCommand] = []
        self.tools: list[PluginTool] = []

    def command(
        self, name: str, *, description: str = "", usage: str = "", host_only: bool = False
    ) -> Callable[[Handler], Handler]:
        if not NAME.match(name):
            raise PluginError(f"invalid command name {name!r}: use a-z, 0-9, - and _")

        def register(handler: Handler) -> Handler:
            if not inspect.iscoroutinefunction(handler):
                raise PluginError(f"the handler of /{name} must be an async function")
            view = PluginCommandView(
                name=name,
                plugin=self._plugin,
                description=description,
                usage=usage or f"/{name}",
                host_only=host_only,
            )
            self.commands.append(PluginCommand(view, handler))
            return handler

        return register

    def tool(
        self,
        name: str,
        *,
        description: str,
        parameters: Mapping[str, JsonValue] | None = None,
        risk: str = "read",
        exposure: str = "deferred",
    ) -> Callable[[ToolHandler], ToolHandler]:
        if not TOOL_NAME.match(name) or name.startswith("mcp__"):
            raise PluginError(f"invalid tool name {name!r}: use a-z, 0-9 and _")
        if risk not in RISKS:
            raise PluginError(f"risk of {name} must be read, write or exec")
        if exposure not in {"core", "deferred"}:
            raise PluginError(f"exposure of {name} must be core or deferred")
        schema = _parameters(parameters)

        def register(handler: ToolHandler) -> ToolHandler:
            if not inspect.iscoroutinefunction(handler):
                raise PluginError(f"the handler of tool {name} must be an async function")
            tool = PluginTool(
                name=name,
                plugin=self._plugin,
                description=description,
                parameters=schema,
                risk=RISKS[risk],
                exposure=Exposure(exposure),
                handler=handler,
                workspace=self._workspace,
            )
            self.tools.append(tool)
            return handler

        return register


class PluginHost:
    def __init__(
        self,
        directory: Path,
        *,
        workspace: Path,
        reserved_tools: Callable[[], Iterable[str]] = lambda: (),
    ) -> None:
        self.directory = directory
        self.workspace = workspace
        self._reserved_tools = reserved_tools
        self._views: tuple[PluginView, ...] = ()
        self._commands: dict[str, PluginCommand] = {}
        self._tools: dict[str, PluginTool] = {}
        self._generation = count()

    def load(self) -> None:
        views: list[PluginView] = []
        commands: dict[str, PluginCommand] = {}
        tools: dict[str, PluginTool] = {}
        reserved = set(self._reserved_tools())
        generation = next(self._generation)
        paths = sorted(self.directory.glob("*.py")) if self.directory.is_dir() else []
        for path in paths:
            name = path.stem
            if name.startswith("_"):
                continue
            try:
                api = PluginApi(name, workspace=self.workspace)
                setup = getattr(_import(path, f"plural_plugin_{generation}_{name}"), "setup", None)
                if not callable(setup):
                    raise PluginError("the file defines no setup(plural) function")
                setup(api)
                for command in api.commands:
                    taken = command.view.name in BUILT_IN or command.view.name in commands
                    if taken or sum(c.view.name == command.view.name for c in api.commands) > 1:
                        raise PluginError(f"/{command.view.name} is already taken")
                for tool in api.tools:
                    taken = tool.name in reserved or tool.name in tools
                    if taken or sum(t.name == tool.name for t in api.tools) > 1:
                        raise PluginError(f"tool {tool.name} is already taken")
            except Exception as error:
                log.warning("plugins.load_failed", plugin=name, error=str(error))
                views.append(
                    PluginView(
                        name=name,
                        path=str(path),
                        status=PluginStatus.FAILED,
                        error=_describe(error),
                    )
                )
                continue
            commands.update((command.view.name, command) for command in api.commands)
            tools.update((tool.name, tool) for tool in api.tools)
            views.append(
                PluginView(
                    name=name,
                    path=str(path),
                    status=PluginStatus.LOADED,
                    commands=tuple(command.view.name for command in api.commands),
                    tools=tuple(tool.name for tool in api.tools),
                )
            )
        self._views = tuple(views)
        self._commands = commands
        self._tools = tools

    def views(self) -> tuple[PluginView, ...]:
        return self._views

    def command_views(self) -> tuple[PluginCommandView, ...]:
        return tuple(command.view for command in self._commands.values())

    def get(self, name: str) -> PluginCommand | None:
        return self._commands.get(name)

    def tools(self) -> tuple[PluginTool, ...]:
        return tuple(self._tools.values())

    def tools_source(self, exposure: Exposure) -> PluginToolSource:
        return PluginToolSource(self, exposure)

    def create(self, name: str) -> Path:
        if not NAME.match(name):
            raise PluginError(f"invalid plugin name {name!r}: use a-z, 0-9, - and _")
        if name in BUILT_IN:
            raise PluginError(f"/{name} is a built-in command")
        path = self.directory / f"{name}.py"
        if path.exists():
            raise PluginError(f"{path} already exists")
        function = name.replace("-", "_")
        if keyword.iskeyword(function):
            function = f"{function}_command"
        self.directory.mkdir(parents=True, exist_ok=True)
        path.write_text(TEMPLATE.format(name=name, function=function), encoding="utf-8")
        return path


def _import(path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise PluginError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[module_name]
        raise
    return module


def _describe(error: Exception) -> str:
    if isinstance(error, SyntaxError):
        return f"SyntaxError line {error.lineno}: {error.msg}"
    if isinstance(error, PluginError):
        return str(error)
    return f"{type(error).__name__}: {error}"
