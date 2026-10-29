import asyncio
from pathlib import Path

import pytest

from plural.host.inbox import Inbox, PluginPrompt, PluginReply
from plural.host.plugins import CommandContext, PluginError, PluginHost
from plural.protocol.models import PluginStatus, Role

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
