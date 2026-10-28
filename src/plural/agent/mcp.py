"""Connects the host to MCP servers and offers their tools to the agent.

Servers come from `.mcp.json` in the workspace and `~/.plural/mcp.json`, in the `mcpServers`
format Claude Code and Cursor use, so a config can be copied or imported as is. Built-in servers,
such as the browser, start first and a configured server of the same name replaces them.
"""

import asyncio
import contextlib
import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Final, cast

import httpx2
import structlog
from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, ImageContent, TextContent
from mcp.types import Tool as McpToolInfo
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from plural.agent.providers.base import ToolSchema
from plural.agent.tools.base import PreparedCall, ToolError, ToolResult
from plural.agent.tools.truncation import truncate_head
from plural.protocol.models import McpServerView, McpStatus, SkillScope, ToolRisk

log = structlog.get_logger(__name__)

PROJECT_FILE: Final = ".mcp.json"
GLOBAL_FILE: Final = (".plural", "mcp.json")
CONNECT_TIMEOUT_S: Final = 45.0
CALL_TIMEOUT_S: Final = 120.0
MAX_TOOL_NAME: Final = 64
SERVER_NAME: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
UNSAFE: Final = re.compile(r"[^A-Za-z0-9_-]")
BROWSER_SERVER: Final = "playwright"
PLAYWRIGHT_MCP: Final = "@playwright/mcp@0.0.83"
BUILTINS_OFF: Final = "disabledBuiltins"


class McpError(Exception):
    pass


class ServerSpec(BaseModel):
    """One `mcpServers` entry: a command to launch, or a URL to reach."""

    model_config = ConfigDict(extra="ignore")

    type: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list[str])
    env: dict[str, str] = Field(default_factory=dict[str, str])
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict[str, str])
    disabled: bool = False

    @property
    def transport(self) -> str:
        return "http" if self.url else "stdio"

    @property
    def secrets(self) -> tuple[str, ...]:
        return tuple(
            value for value in (*self.env.values(), *self.headers.values()) if len(value) >= 8
        )

    def where(self) -> str:
        return self.url or " ".join([self.command or "", *self.args]).strip()


class _ServersFile(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    servers: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue], alias="mcpServers")


class _ClaudeFile(_ServersFile):
    projects: dict[str, _ServersFile] = Field(default_factory=dict[str, _ServersFile])


def _load[M: BaseModel](path: Path, model: type[M]) -> M | None:
    try:
        return model.model_validate_json(path.read_bytes())
    except FileNotFoundError:
        return None
    except (OSError, ValidationError) as error:
        log.warning("mcp.config_unreadable", path=str(path), error=str(error).splitlines()[0])
        return None


def read_config(path: Path) -> dict[str, ServerSpec]:
    parsed = _load(path, _ServersFile)
    return parse_servers(parsed.servers) if parsed is not None else {}


def parse_servers(raw: Mapping[str, JsonValue]) -> dict[str, ServerSpec]:
    found: dict[str, ServerSpec] = {}
    for name, spec in raw.items():
        if not SERVER_NAME.match(name):
            continue
        try:
            parsed = ServerSpec.model_validate(spec)
        except ValidationError:
            continue
        if parsed.command or parsed.url:
            found[name] = parsed
    return found


def write_config(path: Path, servers: Mapping[str, ServerSpec]) -> None:
    data = _raw(path)
    data["mcpServers"] = {
        name: spec.model_dump(exclude_defaults=True) for name, spec in servers.items()
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _raw(path: Path) -> dict[str, object]:
    try:
        loaded: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dict(cast("dict[str, object]", loaded)) if isinstance(loaded, dict) else {}


def disabled_builtins(path: Path) -> frozenset[str]:
    """Built-in servers the host turned off. Only their names are kept, so they stay current."""
    names = _raw(path).get(BUILTINS_OFF)
    return frozenset(cast("list[str]", names)) if isinstance(names, list) else frozenset()


def write_disabled_builtins(path: Path, names: Iterable[str]) -> None:
    data = _raw(path)
    data[BUILTINS_OFF] = sorted(names)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def importable(home: Path, workspace: Path) -> dict[str, ServerSpec]:
    """Servers already configured for Claude Code or Cursor on this machine."""
    found = read_config(home / ".cursor" / "mcp.json")
    claude = _load(home / ".claude.json", _ClaudeFile)
    if claude is not None:
        found |= parse_servers(claude.servers)
        project = claude.projects.get(str(workspace))
        if project is not None:
            found |= parse_servers(project.servers)
    return found


def browser_spec(endpoint: str) -> ServerSpec:
    """Pinned Playwright MCP attached over CDP to a running browser.

    `chrome` finds the host's own Chrome once remote debugging is on in chrome://inspect.
    """
    return ServerSpec(
        command="npx",
        args=["-y", PLAYWRIGHT_MCP, "--cdp-endpoint", endpoint, "--image-responses", "omit"],
    )


def tool_name(server: str, tool: str) -> str:
    name = f"mcp__{server}__{UNSAFE.sub('_', tool)}"
    if len(name) <= MAX_TOOL_NAME:
        return name
    digest = hashlib.sha1(name.encode()).hexdigest()[:6]
    return f"{name[: MAX_TOOL_NAME - 7]}_{digest}"


@dataclass(slots=True)
class _Server:
    name: str
    spec: ServerSpec
    scope: SkillScope
    status: McpStatus = McpStatus.OFF
    error: str | None = None
    tools: dict[str, McpToolInfo] = field(default_factory=dict[str, McpToolInfo])
    client: Client | None = None
    task: asyncio.Task[None] | None = None
    stop: asyncio.Event = field(default_factory=asyncio.Event)

    def view(self) -> McpServerView:
        return McpServerView(
            name=self.name,
            transport=self.spec.transport,
            scope=self.scope,
            status=self.status,
            tools=len(self.tools),
            error=self.error,
        )


class McpTool:
    """An MCP tool as the agent sees it. Every call is an exec: the host is asked first."""

    def __init__(self, hub: "McpHub", server: str, info: McpToolInfo) -> None:
        self._hub = hub
        self._server = server
        self._info = info
        self._name = tool_name(server, info.name)

    @property
    def name(self) -> str:
        return self._name

    def schema(self) -> ToolSchema:
        description = (self._info.description or self._info.name).strip()
        return ToolSchema(
            name=self._name,
            description=f"[{self._server} MCP server] {description}"[:1024],
            parameters=dict(self._info.input_schema or {"type": "object", "properties": {}}),
        )

    def prepare(self, raw: Mapping[str, JsonValue]) -> PreparedCall:
        args = dict(raw)
        return PreparedCall(
            name=self._name,
            risk=ToolRisk.EXEC,
            subject=f"{self._server}/{self._info.name}",
            execute=lambda ctx: self._hub.call(self._server, self._info.name, args),
        )


class McpHub:
    def __init__(
        self,
        *,
        workspace: Path,
        home: Path,
        logs: Path,
        on_change: Callable[[], None] = lambda: None,
        builtin: Mapping[str, ServerSpec] | None = None,
    ) -> None:
        self._workspace = workspace
        self._builtin = dict(builtin or {})
        self._home = home
        self._logs = logs
        self._on_change = on_change
        self._servers: dict[str, _Server] = {}
        self._logfiles: list[IO[str]] = []

    @property
    def project_file(self) -> Path:
        return self._workspace / PROJECT_FILE

    @property
    def global_file(self) -> Path:
        return self._home.joinpath(*GLOBAL_FILE)

    def secrets(self) -> tuple[str, ...]:
        return tuple(secret for server in self._servers.values() for secret in server.spec.secrets)

    def views(self) -> tuple[McpServerView, ...]:
        return tuple(server.view() for server in self._servers.values())

    def tools(self) -> Iterable[McpTool]:
        for server in self._servers.values():
            if server.status is McpStatus.READY:
                for info in server.tools.values():
                    yield McpTool(self, server.name, info)

    def start(self) -> None:
        off = disabled_builtins(self.global_file)
        configured = {
            **{
                name: (spec.model_copy(update={"disabled": name in off}), SkillScope.GLOBAL)
                for name, spec in self._builtin.items()
            },
            **{
                name: (spec, SkillScope.GLOBAL)
                for name, spec in read_config(self.global_file).items()
            },
            **{
                name: (spec, SkillScope.PROJECT)
                for name, spec in read_config(self.project_file).items()
            },
        }
        for name, (spec, scope) in configured.items():
            server = _Server(name=name, spec=spec, scope=scope)
            self._servers[name] = server
            if not spec.disabled:
                self._launch(server)

    async def close(self) -> None:
        for server in self._servers.values():
            server.stop.set()
        tasks = [server.task for server in self._servers.values() if server.task is not None]
        if tasks:
            await asyncio.wait(tasks, timeout=5)
        for handle in self._logfiles:
            handle.close()

    def add(self, name: str, spec: ServerSpec, scope: SkillScope) -> None:
        if not SERVER_NAME.match(name):
            raise McpError("a server name is letters, digits, - and _, up to 32 characters")
        if name in self._servers:
            raise McpError(f"{name} is already connected; remove it first")
        path = self.global_file if scope is SkillScope.GLOBAL else self.project_file
        servers = read_config(path)
        servers[name] = spec
        write_config(path, servers)
        server = _Server(name=name, spec=spec, scope=scope)
        self._servers[name] = server
        self._launch(server)
        self._on_change()

    async def remove(self, name: str) -> None:
        server = self._get(name)
        path = self.global_file if server.scope is SkillScope.GLOBAL else self.project_file
        servers = read_config(path)
        if name in self._builtin and name not in servers:
            raise McpError(f"{name} is built in; turn it off instead")
        await self._halt(server)
        servers.pop(name, None)
        write_config(path, servers)
        del self._servers[name]
        self._on_change()

    async def toggle(self, name: str, *, enabled: bool) -> None:
        server = self._get(name)
        path = self.global_file if server.scope is SkillScope.GLOBAL else self.project_file
        servers = read_config(path)
        if name in servers:
            servers[name] = servers[name].model_copy(update={"disabled": not enabled})
            write_config(path, servers)
        elif name in self._builtin:
            off = disabled_builtins(self.global_file) - {name}
            write_disabled_builtins(self.global_file, off if enabled else off | {name})
        server.spec = server.spec.model_copy(update={"disabled": not enabled})
        if enabled:
            await self._halt(server)
            self._launch(server)
        else:
            await self._halt(server)
            server.status, server.error = McpStatus.OFF, None
        self._on_change()

    async def restart(self, name: str) -> None:
        server = self._get(name)
        await self._halt(server)
        self._launch(server)
        self._on_change()

    def import_servers(self) -> tuple[str, ...]:
        found = importable(self._home, self._workspace)
        fresh = {name: spec for name, spec in found.items() if name not in self._servers}
        if not fresh:
            return ()
        servers = read_config(self.global_file) | fresh
        write_config(self.global_file, servers)
        for name, spec in fresh.items():
            server = _Server(name=name, spec=spec, scope=SkillScope.GLOBAL)
            self._servers[name] = server
            if not spec.disabled:
                self._launch(server)
        self._on_change()
        return tuple(fresh)

    async def call(self, server_name: str, tool: str, args: dict[str, Any]) -> ToolResult:
        server = self._servers.get(server_name)
        if server is None or server.client is None or server.status is not McpStatus.READY:
            raise ToolError(f"the {server_name} MCP server is not connected")
        try:
            result = await asyncio.wait_for(
                server.client.call_tool(tool, args), timeout=CALL_TIMEOUT_S
            )
        except TimeoutError:
            raise ToolError(f"{server_name}/{tool} did not answer in {CALL_TIMEOUT_S:g}s") from None
        except Exception as error:
            raise ToolError(f"{server_name}/{tool} failed: {error}") from None
        return _result(result)

    def _get(self, name: str) -> _Server:
        server = self._servers.get(name)
        if server is None:
            raise McpError(
                f"no MCP server named {name}; have: {', '.join(self._servers) or 'none'}"
            )
        return server

    def _launch(self, server: _Server) -> None:
        server.stop = asyncio.Event()
        server.status, server.error, server.tools = McpStatus.CONNECTING, None, {}
        server.task = asyncio.create_task(self._run(server), name=f"mcp:{server.name}")

    async def _halt(self, server: _Server) -> None:
        server.stop.set()
        if server.task is not None:
            await asyncio.wait([server.task], timeout=5)
            server.task = None

    def _transport(self, server: _Server) -> Any:
        spec = server.spec
        if spec.url:
            return streamable_http_client(
                spec.url,
                http_client=httpx2.AsyncClient(headers=spec.headers, timeout=CALL_TIMEOUT_S),
            )
        self._logs.mkdir(parents=True, exist_ok=True)
        errlog = (self._logs / f"mcp-{server.name}.log").open("a", encoding="utf-8")
        self._logfiles.append(errlog)
        params = StdioServerParameters(
            command=spec.command or "", args=spec.args, env=spec.env or None, cwd=self._workspace
        )
        return stdio_client(params, errlog=errlog)

    async def _run(self, server: _Server) -> None:
        client: Client | None = None
        try:
            client = Client(self._transport(server))
            await asyncio.wait_for(client.__aenter__(), timeout=CONNECT_TIMEOUT_S)
            tools: dict[str, McpToolInfo] = {}
            cursor: str | None = None
            while True:
                listing = await asyncio.wait_for(
                    client.list_tools(cursor=cursor), timeout=CONNECT_TIMEOUT_S
                )
                tools |= {tool.name: tool for tool in listing.tools}
                cursor = listing.next_cursor
                if not cursor:
                    break
            server.client, server.tools, server.status = client, tools, McpStatus.READY
            self._on_change()
            await server.stop.wait()
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            server.status = McpStatus.FAILED
            server.error = _describe(error)
            log.warning("mcp.server_failed", server=server.name, error=server.error)
            self._on_change()
        finally:
            server.client = None
            if client is not None:
                with contextlib.suppress(BaseException):
                    await asyncio.wait_for(client.__aexit__(None, None, None), timeout=5)
            if server.status is McpStatus.READY:
                server.status = McpStatus.OFF
                server.tools = {}


def _describe(failure: BaseException) -> str:
    error: BaseException = failure
    while isinstance(error, BaseExceptionGroup):
        group = cast("BaseExceptionGroup[BaseException]", error)
        if not group.exceptions:
            break
        error = group.exceptions[0]
    if isinstance(error, TimeoutError):
        return "did not answer in time"
    if isinstance(error, FileNotFoundError):
        return f"command not found: {error.filename or error}"
    leaf = cast("BaseException", error)
    text = str(leaf) or type(leaf).__name__
    return text.splitlines()[0][:200]


def _result(result: CallToolResult) -> ToolResult:
    parts: list[str] = []
    for block in result.content:
        if isinstance(block, TextContent):
            parts.append(block.text)
        elif isinstance(block, ImageContent):
            parts.append(f"[image {block.mime_type}]")
        else:
            parts.append(f"[{getattr(block, 'type', 'content')}]")
    if not parts and result.structured_content is not None:
        parts.append(json.dumps(result.structured_content, ensure_ascii=False, indent=2))
    text = truncate_head("\n".join(parts)) or "(no output)"
    if result.is_error:
        raise ToolError(text)
    return ToolResult(text)
