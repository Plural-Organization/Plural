import asyncio
import importlib.util
import inspect
import json
import keyword
import re
import sys
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import count
from pathlib import Path
from types import ModuleType
from typing import Final, Literal, cast

import structlog
from pydantic import JsonValue

from plural.agent.context.compaction import serialize
from plural.agent.loop.events import AgentEvent, Compacted, MessageEnd, ToolEnd, ToolStart
from plural.agent.loop.messages import Message
from plural.agent.prompts import tag
from plural.agent.providers.base import LlmRequest, ToolCallRequest, ToolSchema
from plural.agent.tools.base import PreparedCall, Tool, ToolCtx, ToolResult
from plural.agent.tools.registry import Exposure
from plural.host.inbox import (
    Inbox,
    PluginLineUpdate,
    PluginNotify,
    PluginPrompt,
    PluginQuestion,
    PluginReply,
    PluginShow,
)
from plural.protocol.models import (
    HOST_PARTICIPANT_ID,
    PluginCommandView,
    PluginStatus,
    PluginView,
    Provenance,
    Role,
    ToolCallView,
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
ASK_TIMEOUT_S: Final = 120.0
GUARD_TIMEOUT_S: Final = 5.0
HOOK_TIMEOUT_S: Final = 120.0
MAX_OPTIONS: Final = 20
MAX_STORE_BYTES: Final = 1_000_000
MAX_CONTEXT_CHARS: Final = 8000
# What all plugins together may add to the system prompt.
MAX_INSTRUCTIONS_CHARS: Final = 4000
# What a tool_result hook may hand the model in place of a result.
MAX_RESULT_CHARS: Final = 200_000
# Events a plugin can watch as the agent works, delivered in order in the background.
LIVE_EVENTS: Final = ("message_end", "tool_start", "tool_end", "compaction")
# Live events waiting for plugins; past this, new ones are dropped.
MAX_LIVE_QUEUE: Final = 1000
HOOK_EVENTS: Final = frozenset(
    {
        "session_start",
        "input",
        "before_run",
        "context",
        "tool_args",
        "tool_call",
        "tool_result",
        "summary",
        "run_end",
        *LIVE_EVENTS,
    }
)
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


class PluginStore:
    """A plugin's own JSON values, kept in a file across reloads and restarts.

    Every change is written at once, through a temporary file, so a crash never leaves half a file.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._values: dict[str, JsonValue] | None = None

    def get(self, key: str, default: JsonValue = None) -> JsonValue:
        return self._load().get(key, default)

    def set(self, key: str, value: JsonValue) -> None:
        values = {**self._load(), key: value}
        self._save(values)

    def delete(self, key: str) -> None:
        values = self._load()
        if key in values:
            self._save({name: value for name, value in values.items() if name != key})

    def all(self) -> dict[str, JsonValue]:
        return dict(self._load())

    def _load(self) -> dict[str, JsonValue]:
        if self._values is None:
            try:
                loaded = json.loads(self._path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                loaded = {}
            except (OSError, ValueError) as error:
                raise PluginError(f"cannot read {self._path}: {error}") from None
            self._values = loaded if isinstance(loaded, dict) else {}
        return self._values

    def _save(self, values: dict[str, JsonValue]) -> None:
        try:
            text = json.dumps(values, ensure_ascii=False, indent=2)
        except (TypeError, ValueError) as error:
            raise PluginError(f"store values must be JSON: {error}") from None
        if len(text.encode()) > MAX_STORE_BYTES:
            raise PluginError(f"a plugin's store holds at most {MAX_STORE_BYTES:,} bytes")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(self._path)
        self._values = values


# Answers one question with the session's model: (question, with_history, main_model) -> text.
Asker = Callable[[str, bool, bool], Awaitable[str]]


async def _no_model(question: str, history: bool, main: bool) -> str:
    raise PluginError("no model is available to answer")


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
        asker: Asker = _no_model,
    ) -> None:
        self.command = command
        self.args = args
        self.author = author
        self.author_id = author_id
        self.role = role
        self.workspace = workspace
        self._inbox = inbox
        self._asker = asker

    async def reply(self, text: str) -> None:
        self._inbox.put(PluginReply(self.command, self.author_id, text))

    async def prompt(
        self, text: str, *, follow_up: bool = False, display: str | None = None
    ) -> None:
        """Prompt the agent with `text`; the room sees `display` instead, the full text folded."""
        self._inbox.put(
            PluginPrompt(self.command, self.author_id, text, follow_up=follow_up, display=display)
        )

    async def show(self, title: str, text: str) -> None:
        """Show `text` to the person who ran the command, in a window only they see."""
        self._inbox.put(PluginShow(self.command, self.author_id, title, text))

    async def notify(self, text: str) -> None:
        """A short toast for the person who ran the command; it is not kept anywhere."""
        self._inbox.put(PluginNotify(self.command, self.author_id, text))

    async def confirm(self, title: str) -> bool:
        """Ask the person who ran the command yes or no. Closing it or not answering is no."""
        return await self._question("confirm", title, ("yes", "no")) == "yes"

    async def select(self, title: str, options: Sequence[str]) -> str | None:
        """Let the person who ran the command pick one option; None when they close it."""
        choices = tuple(dict.fromkeys(str(option) for option in options))
        if not choices or len(choices) > MAX_OPTIONS:
            raise PluginError(f"select takes 1 to {MAX_OPTIONS} options")
        return await self._question("select", title, choices)

    async def input(self, title: str, *, default: str = "") -> str | None:
        """Ask the person who ran the command to type a line; None when they close it."""
        return await self._question("input", title, (), default)

    async def _question(
        self, kind: str, title: str, options: tuple[str, ...], default: str = ""
    ) -> str | None:
        answer: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
        self._inbox.put(
            PluginQuestion(self.command, self.author_id, kind, title, options, default, answer)
        )
        return await answer

    async def ask(self, question: str, *, history: bool = True, model: str = "fast") -> str:
        """Ask the session's model one question, outside the conversation, and return its answer.

        With `history` the model sees the conversation so far. Nothing is added to it, the room
        sees nothing, and the model cannot call tools. `model` is "fast" or "main".
        """
        if model not in {"fast", "main"}:
            raise PluginError('model is "fast" or "main"')
        try:
            return await asyncio.wait_for(
                self._asker(question, history, model == "main"), ASK_TIMEOUT_S
            )
        except TimeoutError:
            raise PluginError(f"the model did not answer in {ASK_TIMEOUT_S:g}s") from None

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


class HookContext:
    """What a hook gets besides its event: it may reply to the room and run programs."""

    def __init__(
        self, *, plugin: str, workspace: Path, inbox: Inbox, can_prompt: bool = False
    ) -> None:
        self.plugin = plugin
        self.workspace = workspace
        self._inbox = inbox
        self._can_prompt = can_prompt

    async def reply(self, text: str) -> None:
        self._inbox.put(PluginReply(self.plugin, HOST_PARTICIPANT_ID, text))

    async def prompt(
        self, text: str, *, follow_up: bool = True, display: str | None = None
    ) -> None:
        """From run_end: prompt the agent as the host. That run does not fire run_end again."""
        if not self._can_prompt:
            raise PluginError("only a run_end hook can prompt the agent")
        message = PluginPrompt(
            self.plugin,
            HOST_PARTICIPANT_ID,
            text,
            follow_up=follow_up,
            display=display,
            from_hook=True,
        )
        self._inbox.put(message)

    async def run(self, *argv: str, timeout_s: float = RUN_TIMEOUT_S) -> str:
        return await _run_program(argv, self.workspace, timeout_s)


@dataclass(frozen=True, slots=True)
class Verdict:
    """A tool_call hook's answer. There is no allow: a hook only makes the policy stricter."""

    action: Literal["ask", "deny"]
    reason: str
    plugin: str = ""


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """The session a session_start hook starts in."""

    room: str
    workspace: Path


@dataclass(frozen=True, slots=True)
class PromptInfo:
    """The prompt a run starts with, as a before_run hook sees it."""

    prompt_id: str
    text: str
    author_id: str
    role: str


@dataclass(frozen=True, slots=True)
class RunInfo:
    """A finished run, as a run_end hook sees it."""

    run_id: str
    reason: str
    error: str | None
    author_id: str
    role: str
    files: tuple[str, ...]
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class ToolCall:
    """The tool call a tool_call hook sees, before the policy decides it."""

    name: str
    risk: str
    subject: str
    args: Mapping[str, JsonValue]
    author_id: str
    role: str


@dataclass(frozen=True, slots=True)
class ToolArgs:
    """The tool call a tool_args hook sees, before its arguments are checked."""

    name: str
    args: Mapping[str, JsonValue]
    author_id: str
    role: str


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """A finished tool call, as a tool_result hook sees it before the model does."""

    name: str
    risk: str
    subject: str
    args: Mapping[str, JsonValue]
    content: str
    is_error: bool
    author_id: str
    role: str


@dataclass(slots=True)
class ContextMessage:
    """One message the model is about to be sent. A context hook may change its `content`."""

    role: str
    content: str
    # For a tool result: the tool that gave it.
    tool: str | None = None


@dataclass(frozen=True, slots=True)
class ModelContext:
    """What a context hook sees before a model call: the system prompt, to read, and the
    messages, whose content it may change. Messages cannot be added or removed."""

    system: str
    messages: tuple[ContextMessage, ...]


@dataclass(frozen=True, slots=True)
class MessageInfo:
    """A message_end event: a reply of the agent, whole."""

    run_id: str
    message_id: str
    text: str
    thinking: str


@dataclass(frozen=True, slots=True)
class ToolStartInfo:
    """A tool_start event: a call the agent made, before it is approved and run."""

    run_id: str
    call_id: str
    name: str
    risk: str
    subject: str
    args: Mapping[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ToolEndInfo:
    """A tool_end event: what a call gave back, as the model got it."""

    run_id: str
    call_id: str
    name: str
    content: str
    is_error: bool


@dataclass(frozen=True, slots=True)
class CompactionInfo:
    """A compaction event: the conversation was summarized to make room."""

    run_id: str
    summary: str
    tokens_before: int


@dataclass(frozen=True, slots=True)
class SummaryInfo:
    """What a summary hook gets when the conversation is compacted."""

    # The part being summarized, as text: who said what, which tools ran and what they gave.
    conversation: str
    # The summary the last compaction left, or None.
    previous: str | None
    messages: int


Handler = Callable[[CommandContext], Awaitable[None]]
ToolHandler = Callable[[dict[str, JsonValue], ToolContext], Awaitable[object]]
HookHandler = Callable[[object, HookContext], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class Hook:
    event: str
    plugin: str
    handler: HookHandler


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


# The built-in tools a plugin may run its own way.
REPLACEABLE: Final = frozenset(
    {"read", "write", "edit", "multi_edit", "bash", "grep", "glob", "ls", "web_fetch"}
)


class OverrideContext(ToolContext):
    """What a plugin that runs a built-in tool its own way gets: `original()` runs the built-in."""

    def __init__(
        self,
        *,
        tool: str,
        workspace: Path,
        emit: Callable[[str], None],
        original: Callable[[], Awaitable[ToolResult]],
    ) -> None:
        super().__init__(tool=tool, workspace=workspace, emit=emit)
        self._original = original

    async def original(self) -> str:
        """Run the built-in tool with the call's arguments and return its result. A failure of
        the built-in raises, so a plugin can tell it from an empty result."""
        result = await self._original()
        if result.is_error:
            raise PluginError(result.content)
        return result.content


class OverrideTool:
    """A built-in tool that a plugin runs its own way. The model, the policy and the room see the
    built-in: its schema, risk, subject and folder checks. Only how the call runs changes."""

    replaces = True
    exposure = Exposure.CORE

    def __init__(self, *, name: str, plugin: str, handler: ToolHandler, workspace: Path) -> None:
        self.name = name
        self.plugin = plugin
        self._handler = handler
        self._workspace = workspace
        self.original: Tool | None = None

    def _builtin(self) -> Tool:
        if self.original is None:
            raise PluginError(f"there is no built-in tool {self.name} to replace")
        return self.original

    def schema(self) -> ToolSchema:
        return self._builtin().schema()

    def prepare(self, raw: Mapping[str, JsonValue]) -> PreparedCall:
        prepared = self._builtin().prepare(raw)
        args = dict(raw)

        def execute(ctx: ToolCtx) -> Awaitable[ToolResult]:
            return self._call(args, ctx, prepared)

        return replace(prepared, execute=execute)

    async def _call(
        self, args: dict[str, JsonValue], ctx: ToolCtx, prepared: PreparedCall
    ) -> ToolResult:
        context = OverrideContext(
            tool=self.name,
            workspace=self._workspace,
            emit=ctx.emit,
            original=lambda: prepared.execute(ctx),
        )
        try:
            output = await self._handler(args, context)
        except Exception as error:
            log.warning("plugins.tool_failed", tool=self.name, error=str(error))
            return ToolResult(f"{self.name} failed: {_describe(error)}", is_error=True)
        if output is None:
            # Nothing back: the built-in runs as usual.
            return await prepared.execute(ctx)
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
        tools: list[Tool] = [tool for tool in self._host.tools() if tool.exposure is self._exposure]
        if self._exposure is Exposure.CORE:
            tools.extend(self._host.overrides())
        return tools


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
    def __init__(
        self,
        plugin: str,
        *,
        workspace: Path,
        inbox: Inbox | None = None,
        store: PluginStore | None = None,
    ) -> None:
        self._plugin = plugin
        self.name = plugin
        self._workspace = workspace
        self._inbox = inbox
        self.store = store
        self.commands: list[PluginCommand] = []
        self.tools: list[PluginTool] = []
        self.overrides: list[OverrideTool] = []
        self.hooks: list[Hook] = []
        self.instruction = ""

    def instructions(self, text: str) -> None:
        """Set what this plugin tells the agent in its system prompt; an empty text removes it.

        The agent reads it from the start of its next run on, so a change mid-run waits for the
        run to end."""
        self.instruction = text.strip()

    def on(self, event: str) -> Callable[[HookHandler], HookHandler]:
        if event not in HOOK_EVENTS:
            raise PluginError(f"unknown event {event!r}: use {', '.join(sorted(HOOK_EVENTS))}")

        def register(handler: HookHandler) -> HookHandler:
            if not inspect.iscoroutinefunction(handler):
                raise PluginError(f"the {event} hook must be an async function")
            self.hooks.append(Hook(event, self._plugin, handler))
            return handler

        return register

    def status(self, text: str) -> None:
        """Set this plugin's line in the side panel, such as "tests ✓"; an empty text removes it.

        Everyone in the room sees it. The host shows at most one change a second.
        """
        if self._inbox is not None:
            self._inbox.put(PluginLineUpdate(self._plugin, text))

    def ask(self, reason: str) -> Verdict:
        """From a tool_call hook: have the host approve this call even if the policy allows it."""
        return Verdict("ask", reason, self._plugin)

    def deny(self, reason: str) -> Verdict:
        """From a tool_call hook: refuse this call."""
        return Verdict("deny", reason, self._plugin)

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

    def override(self, name: str) -> Callable[[ToolHandler], ToolHandler]:
        """Run a built-in tool, such as bash or read, with your own function. The model, the
        policy and the room see the built-in; `ctx.original()` runs it, and returning nothing
        lets it run as usual."""
        if name not in REPLACEABLE:
            raise PluginError(
                f"{name} cannot be replaced: use one of {', '.join(sorted(REPLACEABLE))}"
            )

        def register(handler: ToolHandler) -> ToolHandler:
            if not inspect.iscoroutinefunction(handler):
                raise PluginError(f"the handler replacing {name} must be an async function")
            self.overrides.append(
                OverrideTool(
                    name=name, plugin=self._plugin, handler=handler, workspace=self._workspace
                )
            )
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
        inbox: Inbox | None = None,
        reserved_tools: Callable[[], Iterable[str]] = lambda: (),
        builtin_tool: Callable[[str], Tool | None] = lambda name: None,
    ) -> None:
        self.directory = directory
        self._inbox = inbox or Inbox()
        self.workspace = workspace
        self._reserved_tools = reserved_tools
        self._builtin_tool = builtin_tool
        self._overrides: dict[str, OverrideTool] = {}
        self._views: tuple[PluginView, ...] = ()
        self._commands: dict[str, PluginCommand] = {}
        self._tools: dict[str, PluginTool] = {}
        self._hooks: tuple[Hook, ...] = ()
        self._apis: tuple[PluginApi, ...] = ()
        self._live: asyncio.Queue[tuple[str, object]] = asyncio.Queue(MAX_LIVE_QUEUE)
        self._live_worker: asyncio.Task[None] | None = None
        self._call_names: dict[str, str] = {}
        self._generation = count()

    def load(self) -> None:
        views: list[PluginView] = []
        commands: dict[str, PluginCommand] = {}
        tools: dict[str, PluginTool] = {}
        overrides: dict[str, OverrideTool] = {}
        hooks: list[Hook] = []
        apis: list[PluginApi] = []
        reserved = set(self._reserved_tools())
        generation = next(self._generation)
        paths = sorted(self.directory.glob("*.py")) if self.directory.is_dir() else []
        for path in paths:
            name = path.stem
            if name.startswith("_"):
                continue
            try:
                store = PluginStore(self.directory / ".data" / f"{name}.json")
                api = PluginApi(name, workspace=self.workspace, inbox=self._inbox, store=store)
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
                for override in api.overrides:
                    if override.name in overrides or (
                        sum(o.name == override.name for o in api.overrides) > 1
                    ):
                        raise PluginError(f"{override.name} is already replaced by a plugin")
                    override.original = self._builtin_tool(override.name)
                    if override.original is None:
                        raise PluginError(f"there is no built-in tool {override.name} to replace")
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
            overrides.update((override.name, override) for override in api.overrides)
            hooks.extend(api.hooks)
            apis.append(api)
            views.append(
                PluginView(
                    name=name,
                    path=str(path),
                    status=PluginStatus.LOADED,
                    commands=tuple(command.view.name for command in api.commands),
                    tools=(*(tool.name for tool in api.tools), *(o.name for o in api.overrides)),
                )
            )
        self._views = tuple(views)
        self._commands = commands
        self._tools = tools
        self._overrides = overrides
        self._hooks = tuple(hooks)
        self._apis = tuple(apis)

    def describe(self) -> str | None:
        """The plugins' instructions for the system prompt, 4,000 characters at most in all."""
        room = MAX_INSTRUCTIONS_CHARS
        parts: list[str] = []
        for api in self._apis:
            if not api.instruction or room <= 0:
                continue
            text = api.instruction[:room]
            room -= len(text)
            parts.append(tag("plugin", text, name=api.name))
        return "\n".join(parts) or None

    def views(self) -> tuple[PluginView, ...]:
        return self._views

    def command_views(self) -> tuple[PluginCommandView, ...]:
        return tuple(command.view for command in self._commands.values())

    def get(self, name: str) -> PluginCommand | None:
        return self._commands.get(name)

    def tools(self) -> tuple[PluginTool, ...]:
        return tuple(self._tools.values())

    def overrides(self) -> tuple[OverrideTool, ...]:
        """The built-in tools plugins run their own way."""
        return tuple(self._overrides.values())

    def tools_source(self, exposure: Exposure) -> PluginToolSource:
        return PluginToolSource(self, exposure)

    def hooks(self, event: str) -> tuple[Hook, ...]:
        return tuple(hook for hook in self._hooks if hook.event == event)

    def _context(self, plugin: str, *, can_prompt: bool = False) -> HookContext:
        return HookContext(
            plugin=plugin, workspace=self.workspace, inbox=self._inbox, can_prompt=can_prompt
        )

    async def rewrite_input(self, prompt: PromptInfo) -> str:
        """The prompt's text after each input hook had its turn to rewrite it."""
        text = prompt.text
        for hook in self.hooks("input"):
            seen = replace(prompt, text=text)
            try:
                answer = await asyncio.wait_for(
                    hook.handler(seen, self._context(hook.plugin)), GUARD_TIMEOUT_S
                )
            except Exception as error:
                log.warning("plugins.hook_failed", plugin=hook.plugin, error=str(error))
                continue
            if isinstance(answer, str) and answer.strip():
                text = answer[:MAX_RESULT_CHARS]
        return text

    async def before_run(self, prompt: PromptInfo) -> list[tuple[str, str]]:
        """Collect what before_run hooks add for the agent, 8,000 characters at most in all."""
        added: list[tuple[str, str]] = []
        room = MAX_CONTEXT_CHARS
        for hook in self.hooks("before_run"):
            try:
                text = await asyncio.wait_for(
                    hook.handler(prompt, self._context(hook.plugin)), GUARD_TIMEOUT_S
                )
            except Exception as error:
                log.warning("plugins.hook_failed", plugin=hook.plugin, error=str(error))
                continue
            if isinstance(text, str) and text.strip() and room > 0:
                added.append((hook.plugin, text.strip()[:room]))
                room -= len(added[-1][1])
        return added

    async def session_started(self, room: str) -> None:
        """Run every session_start hook after the plugins load, at start and on reload."""
        await self._each("session_start", SessionInfo(room=room, workspace=self.workspace))

    async def run_ended(self, run: RunInfo) -> None:
        """Run every run_end hook in turn; one that fails is reported and the rest still run."""
        await self._each("run_end", run, can_prompt=True)

    async def _each(self, event: str, info: object, *, can_prompt: bool = False) -> None:
        for hook in self.hooks(event):
            context = self._context(hook.plugin, can_prompt=can_prompt)
            try:
                await asyncio.wait_for(hook.handler(info, context), HOOK_TIMEOUT_S)
            except Exception as error:
                log.warning("plugins.hook_failed", plugin=hook.plugin, error=str(error))
                problem = (
                    f"took longer than {HOOK_TIMEOUT_S:g}s"
                    if isinstance(error, TimeoutError)
                    else _describe(error)
                )
                text = f"the {event} hook failed: {problem}"
                self._inbox.put(PluginReply(hook.plugin, HOST_PARTICIPANT_ID, text, ok=False))

    async def tool_args(self, call: ToolCallRequest, provenance: Provenance) -> ToolCallRequest:
        """Let each tool_args hook replace the call's arguments, in turn. The call then goes
        through validation, tool_call hooks and the policy like any other, so a hook cannot
        make a call more permitted than its new arguments are."""
        args: dict[str, JsonValue] = dict(call.args)
        for hook in self.hooks("tool_args"):
            seen = ToolArgs(
                name=call.name,
                args=dict(args),
                author_id=provenance.initiator_id,
                role=provenance.initiator_role.value,
            )
            try:
                answer = await asyncio.wait_for(
                    hook.handler(seen, self._context(hook.plugin)), GUARD_TIMEOUT_S
                )
            except Exception as error:
                log.warning("plugins.hook_failed", plugin=hook.plugin, error=str(error))
                continue
            if answer is None:
                continue
            if not isinstance(answer, Mapping):
                log.warning("plugins.bad_args", plugin=hook.plugin, kind=type(answer).__name__)
                continue
            try:
                args = json.loads(json.dumps(dict(cast("Mapping[str, JsonValue]", answer))))
            except (TypeError, ValueError) as error:
                log.warning("plugins.bad_args", plugin=hook.plugin, error=str(error))
        return call if args == call.args else call.model_copy(update={"args": args})

    async def tool_result(
        self, call: ToolCallView, result: ToolResult, provenance: Provenance
    ) -> ToolResult:
        """Let each tool_result hook replace what the model gets back from a call, in turn."""
        content = result.content
        for hook in self.hooks("tool_result"):
            seen = ToolOutcome(
                name=call.name,
                risk=call.risk.value,
                subject=call.subject,
                args=call.args,
                content=content,
                is_error=result.is_error,
                author_id=provenance.initiator_id,
                role=provenance.initiator_role.value,
            )
            try:
                answer = await asyncio.wait_for(
                    hook.handler(seen, self._context(hook.plugin)), GUARD_TIMEOUT_S
                )
            except Exception as error:
                log.warning("plugins.hook_failed", plugin=hook.plugin, error=str(error))
                continue
            if isinstance(answer, str):
                content = answer[:MAX_RESULT_CHARS]
        if content == result.content:
            return result
        return replace(result, content=content)

    async def request(self, request: LlmRequest) -> LlmRequest:
        """Let each context hook change the text of the messages a model call is sent."""
        hooks = self.hooks("context")
        if not hooks:
            return request
        names = {call.id: call.name for m in request.messages for call in m.tool_calls}
        seen = ModelContext(
            system=request.system,
            messages=tuple(
                ContextMessage(
                    role=m.role,
                    content=m.content,
                    tool=names.get(m.tool_call_id or "") if m.role == "tool" else None,
                )
                for m in request.messages
            ),
        )
        for hook in hooks:
            before = [m.content for m in seen.messages]
            try:
                await asyncio.wait_for(
                    hook.handler(seen, self._context(hook.plugin)), GUARD_TIMEOUT_S
                )
            except Exception as error:
                log.warning("plugins.hook_failed", plugin=hook.plugin, error=str(error))
                for message, content in zip(seen.messages, before, strict=True):
                    message.content = content
                continue
            # Plugin code is not type-checked: text that is not a string is put back.
            for message, content in zip(seen.messages, before, strict=True):
                changed = cast(object, message.content)
                if not isinstance(changed, str):
                    message.content = content
        messages = tuple(
            original
            if view.content == original.content
            else original.model_copy(update={"content": view.content[:MAX_RESULT_CHARS]})
            for original, view in zip(request.messages, seen.messages, strict=True)
        )
        if messages == request.messages:
            return request
        return request.model_copy(update={"messages": messages})

    def observe(self, run_id: str, event: AgentEvent) -> None:
        """Hand an event of the agent's run to the plugins that watch it. They get it in the
        background, in order, so a slow plugin never holds up the room or the agent."""
        match event:
            case ToolStart(call=call):
                self._call_names[call.id] = call.name
                info: tuple[str, object] | None = (
                    "tool_start",
                    ToolStartInfo(
                        run_id, call.id, call.name, call.risk.value, call.subject, call.args
                    ),
                )
            case ToolEnd(call_id=call_id, result=result):
                name = self._call_names.pop(call_id, "")
                info = (
                    "tool_end",
                    ToolEndInfo(run_id, call_id, name, result.content, result.is_error),
                )
            case MessageEnd(message_id=message_id, text=text, thinking=thinking):
                info = ("message_end", MessageInfo(run_id, message_id, text, thinking))
            case Compacted(summary=summary, tokens_before=tokens_before):
                info = ("compaction", CompactionInfo(run_id, summary, tokens_before))
            case _:
                info = None
        if info is None or not self.hooks(info[0]):
            return
        try:
            self._live.put_nowait(info)
        except asyncio.QueueFull:
            log.warning("plugins.live_dropped", event=info[0])
            return
        if self._live_worker is None or self._live_worker.done():
            self._live_worker = asyncio.create_task(self._deliver(), name="plugins-live")

    async def _deliver(self) -> None:
        while True:
            event, info = await self._live.get()
            try:
                for hook in self.hooks(event):
                    try:
                        await asyncio.wait_for(
                            hook.handler(info, self._context(hook.plugin)), GUARD_TIMEOUT_S
                        )
                    except Exception as error:
                        log.warning("plugins.hook_failed", plugin=hook.plugin, error=str(error))
            finally:
                self._live.task_done()

    async def drained(self) -> None:
        """Wait until every live event handed over so far has gone to the plugins."""
        await self._live.join()

    async def summary(self, history: Sequence[Message], previous: str | None) -> str | None:
        """The first summary a summary hook writes for a compaction, or None for the model's."""
        hooks = self.hooks("summary")
        if not hooks:
            return None
        seen = SummaryInfo(
            conversation=serialize(history), previous=previous, messages=len(history)
        )
        for hook in hooks:
            try:
                answer = await asyncio.wait_for(
                    hook.handler(seen, self._context(hook.plugin)), HOOK_TIMEOUT_S
                )
            except Exception as error:
                log.warning("plugins.hook_failed", plugin=hook.plugin, error=str(error))
                continue
            if isinstance(answer, str) and answer.strip():
                return answer.strip()[:MAX_RESULT_CHARS]
        return None

    async def guard_tool(self, call: ToolCallView, provenance: Provenance) -> Verdict | None:
        """Ask every tool_call hook about a call. Any deny wins; a hook that fails counts as ask."""
        seen = ToolCall(
            name=call.name,
            risk=call.risk.value,
            subject=call.subject,
            args=call.args,
            author_id=provenance.initiator_id,
            role=provenance.initiator_role.value,
        )
        asked: Verdict | None = None
        for hook in self.hooks("tool_call"):
            try:
                answer = await asyncio.wait_for(
                    hook.handler(seen, self._context(hook.plugin)), GUARD_TIMEOUT_S
                )
            except TimeoutError:
                answer = Verdict("ask", f"its guard took longer than {GUARD_TIMEOUT_S:g}s")
            except Exception as error:
                log.warning("plugins.hook_failed", plugin=hook.plugin, error=str(error))
                answer = Verdict("ask", f"its guard failed: {_describe(error)}")
            if not isinstance(answer, Verdict):
                continue
            answer = Verdict(answer.action, answer.reason, hook.plugin)
            if answer.action == "deny":
                return answer
            asked = asked or answer
        return asked

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

    def remove(self, name: str) -> Path:
        path = self.directory / f"{name}.py"
        if not NAME.match(name) or not path.is_file():
            raise PluginError(f"no plugin named {name}")
        path.unlink()
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
