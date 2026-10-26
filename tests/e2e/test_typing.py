import asyncio
from pathlib import Path

import pytest

from plural.agent.providers.fake import FakeProvider, reply
from plural.client.connection import CommandRejected
from plural.protocol.commands import PromptSubmit, TypingSet
from plural.protocol.envelope import ErrorCode
from plural.protocol.events import ParticipantTyping, SessionSnapshot
from plural.protocol.models import Role
from tests.e2e.support import Session, running_session


async def test_typing_is_shown_to_everyone_and_stops_on_request(session: Session) -> None:
    owner = await session.owner()
    guest = await session.guest("Alia")
    me = guest.client.projection.me_id

    await guest.client.send(TypingSet(typing=True))
    started = await owner.next(ParticipantTyping)
    assert (started.participant_id, started.typing) == (me, True)

    await guest.client.send(TypingSet(typing=False))
    stopped = await owner.next(ParticipantTyping)
    assert (stopped.participant_id, stopped.typing) == (me, False)


async def test_refreshing_does_not_repeat_the_event(session: Session) -> None:
    owner = await session.owner()
    guest = await session.guest("Alia")
    for _ in range(3):
        await guest.client.send(TypingSet(typing=True))
    await guest.client.send(TypingSet(typing=False))
    await owner.next(ParticipantTyping)
    await owner.next(ParticipantTyping)
    assert [e.typing for e in owner.events if isinstance(e, ParticipantTyping)] == [True, False]


async def test_typing_expires_when_it_is_not_refreshed(tmp_path: Path) -> None:
    provider = FakeProvider([reply("ok")])
    async with running_session(
        tmp_path, relayed=False, provider=provider, overrides={"typing_ttl_s": 0.2}
    ) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        await guest.client.send(TypingSet(typing=True))
        assert (await owner.next(ParticipantTyping)).typing is True
        assert (await owner.next(ParticipantTyping)).typing is False


async def test_sending_the_prompt_ends_typing(session: Session) -> None:
    owner = await session.owner()
    guest = await session.guest("Alia")
    await guest.client.send(TypingSet(typing=True))
    await owner.next(ParticipantTyping)
    await guest.client.send(PromptSubmit(text="hello"))
    assert (await owner.next(ParticipantTyping)).typing is False


async def test_leaving_ends_typing(session: Session) -> None:
    owner = await session.owner()
    guest = await session.guest("Alia")
    await guest.client.send(TypingSet(typing=True))
    await owner.next(ParticipantTyping)
    await guest.stop()
    assert (await owner.next(ParticipantTyping)).typing is False


async def test_a_late_joiner_learns_who_is_typing(session: Session) -> None:
    guest = await session.guest("Alia")
    await guest.client.send(TypingSet(typing=True))
    late = await session.guest("Bek")
    snapshot = next(e for e in late.events if isinstance(e, SessionSnapshot))
    assert snapshot.typing == (guest.client.projection.me_id,)


async def test_viewers_cannot_announce_typing(session: Session) -> None:
    viewer = await session.guest("Eve", Role.VIEWER)
    with pytest.raises(CommandRejected) as rejected:
        await viewer.client.send(TypingSet(typing=True))
    assert rejected.value.error.code is ErrorCode.FORBIDDEN
    await asyncio.sleep(0)
