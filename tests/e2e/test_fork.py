from datetime import UTC, datetime
from pathlib import Path

import pytest

from plural.client.connection import CommandRejected
from plural.protocol.commands import CommandRun, PromptSubmit, SessionFork
from plural.protocol.events import (
    CommandReplied,
    PromptAccepted,
    RunEnded,
    SessionForked,
    SessionSwitch,
)
from plural.storage.sessions import fork_session, list_sessions, read_session, session_path
from tests.doubles import FakeProvider, reply
from tests.e2e.support import ROOM, running_session


async def test_the_host_forks_a_session_before_a_prompt_and_continues_the_fork(
    tmp_path: Path,
) -> None:
    provider = FakeProvider([reply("one done"), reply("two done")])
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        await owner.client.send(PromptSubmit(text="first task"))
        await owner.next(RunEnded)
        await owner.client.send(PromptSubmit(text="second task"))
        second = await owner.next(PromptAccepted)
        await owner.next(RunEnded)

        await owner.client.send(SessionFork(title="try again", before_prompt_id=second.prompt_id))
        forked = await guest.next(SessionForked)
        assert (forked.title, forked.before_prompt_id) == ("try again", second.prompt_id)
        with pytest.raises(CommandRejected):
            await guest.client.send(SessionFork())

    data = tmp_path / "data"
    info = read_session(session_path(data, forked.room))
    assert info is not None
    assert (info.title, info.prompts) == ("try again", 1)
    assert {found.room for found in list_sessions(data)} == {ROOM, forked.room}

    resumed = FakeProvider([reply("another way")])
    async with running_session(
        tmp_path, relayed=False, provider=resumed, overrides={"room": forked.room}
    ) as session:
        owner = await session.owner()
        await owner.client.send(PromptSubmit(text="now try another way"))
        await owner.next(RunEnded)
        sent = [message.content for message in resumed.requests[0].messages]
        assert any("first task" in text for text in sent)
        assert not any("second task" in text for text in sent)


def test_a_fork_needs_a_session_and_a_free_id(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="no session"):
        fork_session(tmp_path, "r_missing1", "r_copy0001", now=now)


SESSIONS = """
def setup(plural):
    @plural.command("branch")
    async def branch(ctx):
        room = await ctx.fork(ctx.args or None, switch=True)
        await ctx.reply(f"forked {room}")

    @plural.command("back")
    async def back(ctx):
        await ctx.switch(ctx.args)
"""


async def test_a_plugin_forks_the_session_and_switches_the_hosts_client(tmp_path: Path) -> None:
    plugins = tmp_path / "data" / "plugins"
    plugins.mkdir(parents=True)
    (plugins / "sessions.py").write_text(SESSIONS)
    async with running_session(tmp_path, relayed=False, provider=FakeProvider()) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        await owner.client.send(CommandRun(name="branch", args="plan B"))
        forked = await guest.next(SessionForked)
        assert (forked.title, forked.switch) == ("plan B", True)

        await owner.client.send(CommandRun(name="back", args=forked.room))
        switch = await owner.next(SessionSwitch)
        assert (switch.room, switch.title) == (forked.room, "plan B")

        # Only the host may: a guest's run of the command fails.
        await guest.client.send(CommandRun(name="branch"))
        failed = await guest.next(CommandReplied)
        while failed.invoker_id == owner.client.projection.me_id:
            failed = await guest.next(CommandReplied)
        assert not failed.ok
        assert "only the host" in failed.text
