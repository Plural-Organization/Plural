import asyncio
import json
from pathlib import Path

import pytest

from plural.agent.providers.base import ToolCallRequest
from plural.agent.sandbox.base import Workspace
from plural.agent.sandbox.local import LocalBackend
from plural.agent.tools.base import ToolCtx, ToolResult
from plural.agent.tools.registry import Exposure
from plural.host import plugins as plugin_module
from plural.host.inbox import Inbox, PluginPrompt, PluginReply
from plural.host.plugins import CommandContext, PluginError, PluginHost
from plural.protocol.models import (
    Origin,
    PluginStatus,
    Provenance,
    Role,
    ToolCallView,
    ToolRisk,
)

HELLO = """
def setup(plural):
    @plural.command("hello", description="Say hello", host_only=True)
    async def hello(ctx):
        await ctx.reply(f"hi {ctx.args}")
"""


def host_with(tmp_path: Path, **files: str) -> PluginHost:
    directory = tmp_path / "plugins"
    directory.mkdir(exist_ok=True)
    for name, source in files.items():
        (directory / f"{name}.py").write_text(source)
    plugins = PluginHost(directory, workspace=tmp_path)
    plugins.load()
    return plugins


def test_a_plugin_registers_its_commands(tmp_path: Path) -> None:
    plugins = host_with(tmp_path, greet=HELLO)
    [view] = plugins.views()
    assert (view.name, view.status, view.commands) == ("greet", PluginStatus.LOADED, ("hello",))
    [command] = plugins.command_views()
    assert (command.name, command.plugin, command.host_only) == ("hello", "greet", True)
    assert command.usage == "/hello"
    assert plugins.get("hello") is not None


def test_broken_plugins_are_listed_and_the_rest_still_load(tmp_path: Path) -> None:
    plugins = host_with(
        tmp_path,
        greet=HELLO,
        syntax="def setup(plural:\n",
        nosetup="x = 1\n",
        crash="def setup(plural):\n    raise RuntimeError('boom')\n",
    )
    status = {view.name: (view.status, view.error) for view in plugins.views()}
    assert status["greet"] == (PluginStatus.LOADED, None)
    assert status["syntax"][0] is PluginStatus.FAILED
    assert str(status["syntax"][1]).startswith("SyntaxError line 1")
    assert status["nosetup"] == (PluginStatus.FAILED, "the file defines no setup(plural) function")
    assert status["crash"] == (PluginStatus.FAILED, "RuntimeError: boom")


def test_command_names_cannot_clash(tmp_path: Path) -> None:
    builtin = "def setup(plural):\n    @plural.command('abort')\n    async def abort(ctx): ...\n"
    plugins = host_with(tmp_path, a_first=HELLO, b_again=HELLO, c_builtin=builtin)
    status = {view.name: view.error for view in plugins.views()}
    assert status == {
        "a_first": None,
        "b_again": "/hello is already taken",
        "c_builtin": "/abort is already taken",
    }


def test_handlers_must_be_async(tmp_path: Path) -> None:
    sync = "def setup(plural):\n    @plural.command('sync')\n    def sync(ctx): ...\n"
    [view] = host_with(tmp_path, sync=sync).views()
    assert view.error == "the handler of /sync must be an async function"


def test_create_writes_a_starter_that_loads(tmp_path: Path) -> None:
    plugins = PluginHost(tmp_path / "plugins", workspace=tmp_path)
    path = plugins.create("deploy-now")
    assert path == tmp_path / "plugins" / "deploy-now.py"
    plugins.load()
    assert [command.name for command in plugins.command_views()] == ["deploy-now"]
    with pytest.raises(PluginError, match="already exists"):
        plugins.create("deploy-now")
    with pytest.raises(PluginError, match="built-in"):
        plugins.create("abort")


def test_remove_deletes_the_file_and_unloads_it(tmp_path: Path) -> None:
    plugins = host_with(tmp_path, greet=HELLO)
    assert plugins.remove("greet") == tmp_path / "plugins" / "greet.py"
    plugins.load()
    assert plugins.views() == ()
    with pytest.raises(PluginError, match="no plugin named greet"):
        plugins.remove("greet")


def test_reload_picks_up_edits(tmp_path: Path) -> None:
    plugins = host_with(tmp_path, greet=HELLO)
    (tmp_path / "plugins" / "greet.py").write_text(HELLO.replace('"hello"', '"hey"'))
    plugins.load()
    assert [command.name for command in plugins.command_views()] == ["hey"]


def context(tmp_path: Path, inbox: Inbox) -> CommandContext:
    return CommandContext(
        command="hello",
        args="there",
        author="Alia",
        author_id="p_alia",
        role=Role.PARTICIPANT,
        workspace=tmp_path,
        inbox=inbox,
    )


async def test_the_context_talks_to_the_actor_through_the_inbox(tmp_path: Path) -> None:
    inbox = Inbox()
    ctx = context(tmp_path, inbox)
    await ctx.reply("hi")
    await ctx.prompt("explain this", follow_up=True)
    assert await inbox.get() == PluginReply("hello", "p_alia", "hi")
    assert await inbox.get() == PluginPrompt("hello", "p_alia", "explain this", follow_up=True)


async def test_run_returns_output_and_reports_failures(tmp_path: Path) -> None:
    ctx = context(tmp_path, Inbox())
    assert (await ctx.run("echo", "ready")).strip() == "ready"
    with pytest.raises(PluginError, match="exited with 3"):
        await ctx.run("sh", "-c", "echo nope >&2; exit 3")
    with pytest.raises(PluginError, match="did not finish"):
        await ctx.run("sleep", "5", timeout_s=0.1)
    await asyncio.sleep(0)


TOOLS = """
def setup(plural):
    @plural.tool("ticket", description="Look up a ticket", parameters={"key": "Ticket key"})
    async def ticket(args, ctx):
        ctx.log("looking")
        return {"key": args["key"], "status": "open"}

    @plural.tool("deploy", description="Deploy", risk="exec", exposure="core")
    async def deploy(args, ctx):
        raise RuntimeError("no deploys on friday")
"""


def test_a_plugin_registers_tools_for_the_registry(tmp_path: Path) -> None:
    plugins = host_with(tmp_path, ops=TOOLS)
    [view] = plugins.views()
    assert view.tools == ("ticket", "deploy")
    deferred = [t.name for t in plugins.tools_source(Exposure.DEFERRED).tools()]
    core = [t.name for t in plugins.tools_source(Exposure.CORE).tools()]
    assert (deferred, core) == (["ticket"], ["deploy"])
    ticket = plugins.tools()[0].schema()
    assert ticket.description == "[ops plugin] Look up a ticket"
    assert ticket.parameters["required"] == ["key"]


async def test_plugin_tools_report_results_and_failures_to_the_model(tmp_path: Path) -> None:
    ticket, deploy = host_with(tmp_path, ops=TOOLS).tools()
    chunks: list[str] = []
    ctx = ToolCtx(workspace=Workspace.at(tmp_path), backend=LocalBackend(), emit=chunks.append)

    found = ticket.prepare({"key": "PLR-1"})
    assert found.risk is ToolRisk.READ
    assert found.subject == '{"key": "PLR-1"}'
    result = await found.execute(ctx)
    assert (result.content, result.is_error) == ('{"key": "PLR-1", "status": "open"}', False)
    assert chunks == ["looking\n"]

    missing = await ticket.prepare({}).execute(ctx)
    assert (missing.content, missing.is_error) == ("missing arguments: key", True)

    failed = await deploy.prepare({}).execute(ctx)
    assert deploy.prepare({}).risk is ToolRisk.EXEC
    assert (failed.content, failed.is_error) == (
        "deploy failed: RuntimeError: no deploys on friday",
        True,
    )


def test_tool_names_cannot_clash(tmp_path: Path) -> None:
    directory = tmp_path / "plugins"
    directory.mkdir()
    (directory / "a.py").write_text(TOOLS)
    (directory / "b.py").write_text(TOOLS)
    (directory / "c.py").write_text(
        "def setup(plural):\n"
        "    @plural.tool('read', description='mine')\n"
        "    async def read(args, ctx): ...\n"
    )
    (directory / "d.py").write_text(
        "def setup(plural):\n"
        "    @plural.tool('x', description='x', risk='root')\n"
        "    async def x(args, ctx): ...\n"
    )
    plugins = PluginHost(directory, workspace=tmp_path, reserved_tools=lambda: {"read"})
    plugins.load()
    assert {view.name: view.error for view in plugins.views()} == {
        "a": None,
        "b": "tool ticket is already taken",
        "c": "tool read is already taken",
        "d": "risk of x must be read, write or exec",
    }


GUARDS = """
import asyncio
import json


def setup(plural):
    @plural.on("tool_call")
    async def careful(call, ctx):
        if call.name == "bash":
            return plural.ask("shell")

    @plural.on("tool_call")
    async def strict(call, ctx):
        if "rm" in call.subject:
            return plural.deny("no deleting")
        if call.name == "slow":
            await asyncio.sleep(1)
"""

BASH = ToolCallView(id="c", name="bash", risk=ToolRisk.EXEC, subject="rm -rf build", args={})
HOST = Provenance(initiator_id="p_host", initiator_role=Role.HOST, origin=Origin.DIRECT)


async def test_tool_call_hooks_can_ask_or_deny_and_deny_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugins = host_with(tmp_path, guards=GUARDS)
    denied = await plugins.guard_tool(BASH, HOST)
    assert denied is not None
    assert (denied.action, denied.reason, denied.plugin) == ("deny", "no deleting", "guards")
    listing = BASH.model_copy(update={"subject": "ls"})
    asked = await plugins.guard_tool(listing, HOST)
    assert asked is not None
    assert (asked.action, asked.reason) == ("ask", "shell")
    read = BASH.model_copy(update={"name": "read", "risk": ToolRisk.READ, "subject": "a.txt"})
    assert await plugins.guard_tool(read, HOST) is None

    monkeypatch.setattr(plugin_module, "GUARD_TIMEOUT_S", 0.05)
    slow = await plugins.guard_tool(read.model_copy(update={"name": "slow"}), HOST)
    assert slow is not None
    assert (slow.action, slow.reason) == ("ask", "its guard took longer than 0.05s")


def test_hooks_need_a_known_event_and_an_async_handler(tmp_path: Path) -> None:
    unknown = "def setup(plural):\n    @plural.on('tool_called')\n    async def h(e, c): ...\n"
    sync = "def setup(plural):\n    @plural.on('run_end')\n    def h(e, c): ...\n"
    views = host_with(tmp_path, unknown=unknown, sync=sync).views()
    errors = {view.name: view.error for view in views}
    assert errors["sync"] == "the run_end hook must be an async function"
    assert errors["unknown"] is not None
    assert errors["unknown"].startswith("unknown event 'tool_called'")


FAILING_AFTER = """
def setup(plural):
    @plural.on("run_end")
    async def broken(run, ctx):
        raise ValueError("nope")

    @plural.on("run_end")
    async def fine(run, ctx):
        await ctx.prompt("again")

    @plural.on("tool_call")
    async def eager(call, ctx):
        await ctx.prompt("not allowed here")
"""


async def test_run_end_hooks_report_failures_and_only_they_can_prompt(tmp_path: Path) -> None:
    inbox = Inbox()
    directory = tmp_path / "plugins"
    directory.mkdir()
    (directory / "after.py").write_text(FAILING_AFTER)
    plugins = PluginHost(directory, workspace=tmp_path, inbox=inbox)
    plugins.load()
    run = plugin_module.RunInfo(
        run_id="r",
        reason="stop",
        error=None,
        author_id="p_host",
        role="host",
        files=(),
        input_tokens=0,
        output_tokens=0,
    )
    await plugins.run_ended(run)
    failed = await inbox.get()
    assert failed == PluginReply(
        "after", "p_host", "the run_end hook failed: ValueError: nope", ok=False
    )
    prompted = await inbox.get()
    assert isinstance(prompted, PluginPrompt)
    assert (prompted.text, prompted.from_hook, prompted.follow_up) == ("again", True, True)

    asked = await plugins.guard_tool(BASH, HOST)
    assert asked is not None
    assert asked.reason == "its guard failed: only a run_end hook can prompt the agent"


COUNTER = """
def setup(plural):
    @plural.command("count")
    async def count(ctx):
        plural.store.set("runs", plural.store.get("runs", 0) + 1)
        await ctx.reply(str(plural.store.get("runs")))
"""


async def test_a_plugin_store_survives_a_reload(tmp_path: Path) -> None:
    inbox = Inbox()
    plugins = host_with(tmp_path, counter=COUNTER)
    for _ in range(2):
        command = plugins.get("count")
        assert command is not None
        await command.handler(context(tmp_path, inbox))
        plugins.load()
    saved = tmp_path / "plugins" / ".data" / "counter.json"
    assert json.loads(saved.read_text()) == {"runs": 2}
    assert [view.name for view in plugins.views()] == ["counter"]


def test_a_store_keeps_json_and_refuses_the_rest(tmp_path: Path) -> None:
    store = plugin_module.PluginStore(tmp_path / "s.json")
    store.set("seen", ["a", "b"])
    store.delete("missing")
    assert store.all() == {"seen": ["a", "b"]}
    with pytest.raises(PluginError, match="must be JSON"):
        store.set("bad", object())  # pyright: ignore[reportArgumentType]
    assert plugin_module.PluginStore(tmp_path / "s.json").get("seen") == ["a", "b"]
    store.delete("seen")
    assert plugin_module.PluginStore(tmp_path / "s.json").all() == {}


ARGS = """
def setup(plural):
    @plural.on("tool_args")
    async def uv(call, ctx):
        if call.name == "bash":
            command = call.args["command"].replace("pip install", "uv pip install")
            return {**call.args, "command": command}

    @plural.on("tool_args")
    async def quiet(call, ctx):
        if call.name == "bash":
            return {**call.args, "command": call.args["command"] + " -q"}

    @plural.on("tool_args")
    async def nothing(call, ctx):
        return None

    @plural.on("tool_args")
    async def broken(call, ctx):
        raise RuntimeError("boom")

    @plural.on("tool_args")
    async def wrong(call, ctx):
        return "not a mapping"
"""


async def test_tool_args_hooks_change_the_arguments_in_turn(tmp_path: Path) -> None:
    plugins = host_with(tmp_path, args=ARGS)
    call = ToolCallRequest(id="c1", name="bash", args={"command": "pip install x"})
    changed = await plugins.tool_args(call, HOST)
    assert changed.id == "c1"
    assert changed.args == {"command": "uv pip install x -q"}
    # A hook that fails or answers with something else leaves the arguments as they were.
    read = ToolCallRequest(id="c2", name="read", args={"path": "a.txt"})
    assert await plugins.tool_args(read, HOST) is read


RESULTS = """
def setup(plural):
    @plural.on("tool_result")
    async def redact(result, ctx):
        if "SECRET" in result.content:
            return result.content.replace("SECRET", "[hidden]")

    @plural.on("tool_result")
    async def hint(result, ctx):
        if result.is_error and result.name == "bash":
            return result.content + "\\nhint: run make setup first"

    @plural.on("tool_result")
    async def broken(result, ctx):
        raise RuntimeError("boom")

    @plural.on("tool_result")
    async def wrong(result, ctx):
        return 42
"""


async def test_tool_result_hooks_change_what_the_model_gets(tmp_path: Path) -> None:
    plugins = host_with(tmp_path, results=RESULTS)
    failed = ToolResult("token SECRET missing", is_error=True)
    changed = await plugins.tool_result(BASH, failed, HOST)
    assert changed.content == "token [hidden] missing\nhint: run make setup first"
    assert changed.is_error
    # Hooks that change nothing, fail or answer with something else leave the result as it was.
    plain = ToolResult("ok")
    assert await plugins.tool_result(BASH, plain, HOST) is plain
