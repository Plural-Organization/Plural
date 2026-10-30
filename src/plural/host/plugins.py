import asyncio
import importlib.util
import inspect
import keyword
import re
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from types import ModuleType
from typing import Final

import structlog

from plural.host.inbox import Inbox, PluginPrompt, PluginReply
from plural.protocol.models import PluginCommandView, PluginStatus, PluginView, Role

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
        if not argv:
            raise PluginError("run() needs a program to start")
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=self.workspace,
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


@dataclass(frozen=True, slots=True)
class PluginCommand:
    view: PluginCommandView
    handler: Handler


class PluginApi:
    def __init__(self, plugin: str) -> None:
        self._plugin = plugin
        self.commands: list[PluginCommand] = []

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


class PluginHost:
    def __init__(self, directory: Path, *, workspace: Path) -> None:
        self.directory = directory
        self.workspace = workspace
        self._views: tuple[PluginView, ...] = ()
        self._commands: dict[str, PluginCommand] = {}
        self._generation = count()

    def load(self) -> None:
        views: list[PluginView] = []
        commands: dict[str, PluginCommand] = {}
        generation = next(self._generation)
        paths = sorted(self.directory.glob("*.py")) if self.directory.is_dir() else []
        for path in paths:
            name = path.stem
            if name.startswith("_"):
                continue
            try:
                api = PluginApi(name)
                setup = getattr(_import(path, f"plural_plugin_{generation}_{name}"), "setup", None)
                if not callable(setup):
                    raise PluginError("the file defines no setup(plural) function")
                setup(api)
                for command in api.commands:
                    taken = command.view.name in BUILT_IN or command.view.name in commands
                    if taken or sum(c.view.name == command.view.name for c in api.commands) > 1:
                        raise PluginError(f"/{command.view.name} is already taken")
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
            views.append(
                PluginView(
                    name=name,
                    path=str(path),
                    status=PluginStatus.LOADED,
                    commands=tuple(command.view.name for command in api.commands),
                )
            )
        self._views = tuple(views)
        self._commands = commands

    def views(self) -> tuple[PluginView, ...]:
        return self._views

    def command_views(self) -> tuple[PluginCommandView, ...]:
        return tuple(command.view for command in self._commands.values())

    def get(self, name: str) -> PluginCommand | None:
        return self._commands.get(name)

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
