from pathlib import Path

import pytest

from plural.agent.providers.fake import FakeProvider, reply
from plural.client.connection import CommandRejected
from plural.protocol.commands import CommandRun, PluginsCreate, PluginsReload
from plural.protocol.envelope import ErrorCode
from plural.protocol.events import (
    CommandInvoked,
    CommandReplied,
    PluginsChanged,
    PromptAccepted,
    RunEnded,
)
from plural.protocol.models import PluginStatus, Role
from tests.e2e.support import running_session

PLUGIN = """
def setup(plural):
    @plural.command("hello", description="Say hello")
    async def hello(ctx):
        await ctx.reply(f"hi {ctx.author}: {ctx.args}")

    @plural.command("ask", description="Ask the agent")
    async def ask(ctx):
        await ctx.prompt(f"please {ctx.args}")

    @plural.command("deploy", host_only=True)
    async def deploy(ctx):
        await ctx.reply("deployed")

    @plural.command("broken")
    async def broken(ctx):
        raise ValueError("nope")
"""


def install(tmp_path: Path, name: str, source: str) -> None:
    directory = tmp_path / "data" / "plugins"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.py").write_text(source)


async def test_everyone_sees_plugin_commands_and_their_replies(tmp_path: Path) -> None:
    install(tmp_path, "team", PLUGIN)
    async with running_session(tmp_path, relayed=False, provider=FakeProvider()) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        names = [command.name for command in guest.client.projection.state.commands]
        assert names == ["hello", "ask", "deploy", "broken"]

        await guest.client.send(CommandRun(name="hello", args="there"))
        invoked = await owner.next(CommandInvoked)
        assert (invoked.command, invoked.args) == ("hello", "there")
        replied = await owner.next(CommandReplied)
        assert (replied.text, replied.ok) == ("hi Alia: there", True)

        with pytest.raises(CommandRejected) as rejected:
            await guest.client.send(CommandRun(name="deploy"))
        assert rejected.value.error.code is ErrorCode.FORBIDDEN
        await owner.client.send(CommandRun(name="deploy"))
        assert (await owner.next(CommandReplied)).text == "deployed"

        await guest.client.send(CommandRun(name="broken"))
        failed = await owner.next(CommandReplied)
        assert not failed.ok
        assert failed.text == "/broken failed: ValueError: nope"

        with pytest.raises(CommandRejected) as missing:
            await guest.client.send(CommandRun(name="nothing"))
        assert missing.value.error.code is ErrorCode.NOT_FOUND


async def test_a_plugin_prompt_belongs_to_whoever_ran_the_command(tmp_path: Path) -> None:
    install(tmp_path, "team", PLUGIN)
    provider = FakeProvider([reply("done")])
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        await guest.client.send(CommandRun(name="ask", args="check the tests"))
        accepted = await owner.next(PromptAccepted)
        assert accepted.text == "please check the tests"
        assert accepted.author_id == guest.client.projection.me_id
        assert accepted.provenance.initiator_role is Role.PARTICIPANT
        await owner.next(RunEnded)


async def test_viewers_cannot_run_commands(tmp_path: Path) -> None:
    install(tmp_path, "team", PLUGIN)
    async with running_session(tmp_path, relayed=False, provider=FakeProvider()) as session:
        viewer = await session.guest("Vic", role=Role.VIEWER)
        with pytest.raises(CommandRejected) as rejected:
            await viewer.client.send(CommandRun(name="hello"))
        assert rejected.value.error.code is ErrorCode.FORBIDDEN


async def test_the_host_creates_and_reloads_plugins(tmp_path: Path) -> None:
    async with running_session(tmp_path, relayed=False, provider=FakeProvider()) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        with pytest.raises(CommandRejected) as rejected:
            await guest.client.send(PluginsCreate(name="notes"))
        assert rejected.value.error.code is ErrorCode.FORBIDDEN

        await owner.client.send(PluginsCreate(name="notes"))
        await owner.next(PluginsChanged)
        changed = await guest.next(PluginsChanged)
        assert [(view.name, view.status) for view in changed.plugins] == [
            ("notes", PluginStatus.LOADED)
        ]
        await guest.client.send(CommandRun(name="notes", args="x"))
        assert (await guest.next(CommandReplied)).text == "Hello Alia! You wrote: x"

        with pytest.raises(CommandRejected) as again:
            await owner.client.send(PluginsCreate(name="notes"))
        assert again.value.error.code is ErrorCode.CONFLICT

        install(tmp_path, "notes", "def setup(plural):\n    raise RuntimeError('oops')\n")
        await owner.client.send(PluginsReload())
        reloaded = await owner.next(PluginsChanged)
        assert reloaded.plugins[0].error == "RuntimeError: oops"
        assert reloaded.commands == ()
