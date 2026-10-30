import asyncio
from pathlib import Path

import pytest

from plural.agent.sandbox.base import Workspace
from plural.agent.sandbox.local import LocalBackend
from plural.agent.tools.base import ToolCtx
from plural.agent.tools.registry import Exposure
from plural.host.inbox import Inbox, PluginPrompt, PluginReply
from plural.host.plugins import CommandContext, PluginError, PluginHost
from plural.protocol.models import PluginStatus, Role, ToolRisk

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
