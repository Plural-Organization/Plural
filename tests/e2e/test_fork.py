from datetime import UTC, datetime
from pathlib import Path

import pytest

from plural.client.connection import CommandRejected
from plural.protocol.commands import PromptSubmit, SessionFork
from plural.protocol.events import PromptAccepted, RunEnded, SessionForked
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
