import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from plural.agent.providers.fake import FakeProvider, reply
from plural.client.connection import CommandRejected
from plural.client.reconnect import JoinLink, SessionClient
from plural.protocol.commands import ChatSend, PromptSubmit
from plural.protocol.envelope import ErrorCode
from plural.protocol.events import ChatPosted, RunEnded, SessionSnapshot
from plural.protocol.models import Role
from tests.e2e.support import CLIENT, Session, Watcher, running_session

SECRET = "the budget is 40k and we say nothing to the agent"


@pytest.fixture(params=["direct", "relay"])
async def room(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncGenerator[Session]:
    provider = FakeProvider([reply("noted")])
    async with running_session(
        tmp_path, relayed=request.param == "relay", provider=provider
    ) as running:
        yield running


def posted(watcher: Watcher) -> list[ChatPosted]:
    return [event for event in watcher.events if isinstance(event, ChatPosted)]


async def rejected(watcher: Watcher, command: ChatSend) -> ErrorCode:
    with pytest.raises(CommandRejected) as caught:
        await watcher.client.send(command)
    return caught.value.error.code


async def settle() -> None:
    await asyncio.sleep(0.3)


async def test_a_team_message_reaches_everyone_in_the_room(room: Session) -> None:
    owner = await room.owner()
    alia = await room.guest("Alia")
    viewer = await room.guest("Bek", Role.VIEWER)

    await alia.client.send(ChatSend(text="standup in five"))
    first = await owner.next(ChatPosted)
    await viewer.next(ChatPosted)

    assert (first.text, first.author_id, first.to) == (
        "standup in five",
        alia.client.projection.me_id,
        None,
    )
    assert [e.text for e in posted(alia)] == ["standup in five"]
    assert [entry.text for entry in owner.client.projection.state.chat] == ["standup in five"]


async def test_a_private_message_reaches_only_the_person_and_the_sender(room: Session) -> None:
    owner = await room.owner()
    alia = await room.guest("Alia")
    bek = await room.guest("Bek")
    bek_id = bek.client.projection.me_id
    assert bek_id is not None

    await alia.client.send(ChatSend(text="can you cover my review", to=bek_id))
    heard = await bek.next(ChatPosted)
    await alia.next(ChatPosted)
    await settle()

    assert heard.to == bek_id
    assert posted(owner) == []
    assert owner.client.projection.state.chat == ()
    assert len(posted(bek)) == 1
    assert len(posted(alia)) == 1


async def test_a_private_message_waits_for_the_person_who_was_away(room: Session) -> None:
    alia = await room.guest("Alia")
    bek = await room.guest("Bek")
    bek_id = bek.client.projection.me_id
    token = bek.client._token  # pyright: ignore[reportPrivateUsage]
    assert bek_id is not None
    assert token is not None
    await bek.stop()

    await alia.client.send(ChatSend(text="read this when you are back", to=bek_id))
    await alia.client.send(ChatSend(text="and a note for everyone"))
    await alia.next(ChatPosted)

    link = JoinLink.parse(room.host.host_link)
    returning = Watcher(
        SessionClient(
            JoinLink(url=link.url, room=link.room, token=token), name="Bek", client=CLIENT
        )
    )
    room.watchers.append(returning)
    await returning.next(SessionSnapshot)
    chat = returning.client.projection.state.chat
    assert [entry.text for entry in chat] == [
        "read this when you are back",
        "and a note for everyone",
    ]
    assert chat[0].to == bek_id


async def test_a_newcomer_gets_the_team_chat_but_not_what_was_private(room: Session) -> None:
    alia = await room.guest("Alia")
    bek = await room.guest("Bek")
    bek_id = bek.client.projection.me_id
    assert bek_id is not None
    await alia.client.send(ChatSend(text="for Bek only", to=bek_id))
    await alia.client.send(ChatSend(text="for the room"))
    await bek.next(ChatPosted)

    cleo = await room.guest("Cleo")
    await asyncio.sleep(0.3)
    assert [entry.text for entry in cleo.client.projection.state.chat] == ["for the room"]


async def test_the_model_never_gets_the_chat(tmp_path: Path) -> None:
    provider = FakeProvider([reply("noted")])
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        alia = await session.guest("Alia")
        alia_id = alia.client.projection.me_id
        assert alia_id is not None
        await owner.client.send(ChatSend(text=SECRET))
        await owner.client.send(ChatSend(text=f"{SECRET} (private)", to=alia_id))
        await owner.client.send(PromptSubmit(text="summarize notes.txt"))
        await owner.next(RunEnded)

        assert provider.requests
        for request in provider.requests:
            assert SECRET not in request.system
            for message in request.messages:
                assert SECRET not in message.content


async def test_a_watcher_reads_the_team_chat_but_cannot_write_or_be_written_to(
    room: Session,
) -> None:
    owner = await room.owner()
    viewer = await room.guest("Bek", Role.VIEWER)
    viewer_id = viewer.client.projection.me_id
    assert viewer_id is not None

    assert await rejected(viewer, ChatSend(text="hello")) is ErrorCode.FORBIDDEN
    assert await rejected(owner, ChatSend(text="psst", to=viewer_id)) is ErrorCode.INVALID

    await owner.client.send(ChatSend(text="welcome"))
    assert (await viewer.next(ChatPosted)).text == "welcome"


async def test_a_message_needs_a_real_recipient_and_a_real_mention(room: Session) -> None:
    owner = await room.owner()
    owner_id = owner.client.projection.me_id
    assert owner_id is not None

    assert await rejected(owner, ChatSend(text="x", to="p_nobody")) is ErrorCode.NOT_FOUND
    assert await rejected(owner, ChatSend(text="x", to=owner_id)) is ErrorCode.INVALID
    assert await rejected(owner, ChatSend(text="x", mentions=("p_nobody",))) is ErrorCode.NOT_FOUND


async def test_a_mention_is_carried_once_and_seen_by_all(room: Session) -> None:
    owner = await room.owner()
    alia = await room.guest("Alia")
    alia_id = alia.client.projection.me_id
    assert alia_id is not None

    await owner.client.send(ChatSend(text="@Alia look", mentions=(alia_id, alia_id)))
    seen = await alia.next(ChatPosted)
    assert seen.mentions == (alia_id,)
    assert seen.to is None
