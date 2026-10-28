import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest

from plural.agent.providers.fake import FakeProvider, reply
from plural.client.connection import CommandRejected
from plural.client.reconnect import JoinLink, SessionClient
from plural.host.bootstrap import build_host
from plural.host.config import HostSettings
from plural.protocol.commands import AdmissionSet, InviteCreate, JoinDecide, LinkRevoke
from plural.protocol.envelope import ErrorCode
from plural.protocol.events import (
    InviteCreated,
    JoinPending,
    JoinRequested,
    JoinResolved,
    ParticipantJoined,
    SessionSnapshot,
    SessionWelcome,
)
from plural.protocol.models import AdmissionMode, JoinDecision, Role
from tests.e2e.support import (
    CLIENT,
    ROOM,
    RelayServer,
    Session,
    Watcher,
    free_port,
    running_session,
)

KNOCK_TIMEOUT = 0.4


@pytest.fixture(params=["direct", "relay"])
async def room(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncGenerator[Session]:
    provider = FakeProvider([reply("ok")])
    async with running_session(
        tmp_path, relayed=request.param == "relay", provider=provider
    ) as running:
        yield running


def knock(session: Session, name: str, link: str | None = None) -> Watcher:
    target = link or session.host.room_link.link
    watcher = Watcher(SessionClient(JoinLink.parse(target), name=name, client=CLIENT))
    session.watchers.append(watcher)
    return watcher


async def failure(watcher: Watcher, timeout: float = 5) -> CommandRejected:
    async with asyncio.timeout(timeout):
        while not watcher._task.done():  # pyright: ignore[reportPrivateUsage]
            await asyncio.sleep(0.02)
    error = watcher._task.exception()  # pyright: ignore[reportPrivateUsage]
    assert isinstance(error, CommandRejected)
    return error


async def settle() -> None:
    await asyncio.sleep(0.3)


async def test_someone_with_the_room_link_waits_until_the_host_lets_them_in(room: Session) -> None:
    owner = await room.owner()
    alia = knock(room, "Alia")

    await alia.next(JoinPending)
    asked = await owner.next(JoinRequested)
    assert asked.request.name == "Alia"
    assert not any(isinstance(event, SessionWelcome) for event in alia.events)
    assert alia.client.projection.waiting is True
    assert list(owner.client.projection.state.join_requests) == [asked.request.id]

    await owner.client.send(JoinDecide(request_id=asked.request.id, decision="allow"))
    welcome = await alia.next(SessionWelcome)
    await alia.next(SessionSnapshot)
    assert welcome.participant.role is Role.PARTICIPANT
    assert alia.client.projection.waiting is False
    assert (await owner.next(JoinResolved)).decision is JoinDecision.ALLOW
    assert owner.client.projection.state.join_requests == {}
    assert owner.client.projection.state.participants[welcome.participant.id].connected


async def test_the_host_can_let_someone_in_as_a_viewer(room: Session) -> None:
    owner = await room.owner()
    bek = knock(room, "Bek")
    asked = await owner.next(JoinRequested)
    await owner.client.send(JoinDecide(request_id=asked.request.id, decision="viewer"))
    assert (await bek.next(SessionWelcome)).participant.role is Role.VIEWER


async def test_a_refusal_ends_the_wait_and_is_not_retried(room: Session) -> None:
    owner = await room.owner()
    cleo = knock(room, "Cleo")
    asked = await owner.next(JoinRequested)
    await owner.client.send(JoinDecide(request_id=asked.request.id, decision="deny"))

    error = await failure(cleo)
    assert error.error.code is ErrorCode.FORBIDDEN
    assert "did not let you in" in error.error.message
    await settle()
    assert len([e for e in owner.events if isinstance(e, JoinRequested)]) == 1
    assert not any(isinstance(event, SessionWelcome) for event in cleo.events)


async def test_only_the_host_sees_who_is_waiting_and_only_the_host_decides(room: Session) -> None:
    owner = await room.owner()
    alia = knock(room, "Alia")
    asked = await owner.next(JoinRequested)
    await owner.client.send(JoinDecide(request_id=asked.request.id, decision="allow"))
    await alia.next(SessionSnapshot)

    bek = knock(room, "Bek")
    second = await owner.next(JoinRequested)
    await settle()
    assert not any(isinstance(event, JoinRequested | JoinResolved) for event in alia.events)
    assert alia.client.projection.state.join_requests == {}
    with pytest.raises(CommandRejected) as caught:
        await alia.client.send(JoinDecide(request_id=second.request.id, decision="allow"))
    assert caught.value.error.code is ErrorCode.FORBIDDEN
    assert list(owner.client.projection.state.join_requests) == [second.request.id]
    assert bek.client.projection.waiting is True


async def test_a_one_time_invite_and_a_saved_token_need_no_approval(room: Session) -> None:
    owner = await room.owner()
    guest = await room.guest("Alia")
    await guest.stop()
    await settle()
    assert not any(isinstance(event, JoinRequested) for event in owner.events)
    assert guest.client.projection.me is not None


async def test_someone_who_was_let_in_comes_back_without_asking_again(room: Session) -> None:
    owner = await room.owner()
    alia = knock(room, "Alia")
    asked = await owner.next(JoinRequested)
    await owner.client.send(JoinDecide(request_id=asked.request.id, decision="allow"))
    welcome = await alia.next(SessionWelcome)
    token = welcome.token
    await alia.stop()
    await settle()

    link = JoinLink.parse(room.host.host_link)
    again = Watcher(
        SessionClient(
            JoinLink(url=link.url, room=link.room, token=token), name="Alia", client=CLIENT
        )
    )
    room.watchers.append(again)
    await again.next(SessionWelcome)
    assert len([e for e in owner.events if isinstance(e, JoinRequested)]) == 1


async def test_the_link_serves_many_people_one_after_another(room: Session) -> None:
    owner = await room.owner()
    names = ("Alia", "Bek", "Cleo")
    for name in names:
        watcher = knock(room, name)
        asked = await owner.next(JoinRequested)
        assert asked.request.name == name
        await owner.client.send(JoinDecide(request_id=asked.request.id, decision="allow"))
        await watcher.next(SessionWelcome)
    joined = [e.participant.name for e in owner.events if isinstance(e, ParticipantJoined)]
    assert {"Alia", "Bek", "Cleo"} <= set(joined)


async def test_with_the_room_open_the_link_lets_people_straight_in(room: Session) -> None:
    owner = await room.owner()
    await owner.client.send(AdmissionSet(mode=AdmissionMode.OPEN))
    dana = knock(room, "Dana")
    welcome = await dana.next(SessionWelcome)
    assert welcome.participant.role is Role.PARTICIPANT
    assert not any(isinstance(event, JoinRequested) for event in owner.events)
    assert owner.client.projection.state.admission is AdmissionMode.OPEN

    await owner.client.send(AdmissionSet(mode=AdmissionMode.APPROVE))
    eve = knock(room, "Eve")
    await eve.next(JoinPending)
    await owner.next(JoinRequested)


async def test_withdrawing_the_link_refuses_those_waiting_and_kills_the_old_link(
    room: Session,
) -> None:
    owner = await room.owner()
    old = room.host.room_link.link
    waiting = knock(room, "Fay")
    await owner.next(JoinRequested)

    await owner.client.send(LinkRevoke())
    assert (await owner.next(JoinResolved)).decision is JoinDecision.REVOKED
    created = await owner.next(InviteCreated)
    assert created.reusable is True
    assert created.link != old

    error = await failure(waiting)
    assert "withdrawn" in error.error.message

    stale = knock(room, "Gus", link=old)
    assert (await failure(stale)).error.code is ErrorCode.UNAUTHORIZED
    fresh = knock(room, "Hal", link=created.link)
    await fresh.next(JoinPending)


async def test_the_room_link_can_be_asked_for_again_and_stays_the_same(room: Session) -> None:
    owner = await room.owner()
    await owner.client.send(InviteCreate(reusable=True))
    first = await owner.next(InviteCreated)
    await owner.client.send(InviteCreate(reusable=True))
    second = await owner.next(InviteCreated)
    assert first.link == second.link == room.host.room_link.link
    assert first.reusable
    assert first.expires_at is None


async def test_a_wrong_link_code_is_refused(room: Session) -> None:
    await room.owner()
    link = JoinLink.parse(room.host.room_link.link)
    bogus = knock(room, "Ivy", link=f"{link.url}?join=not-the-code")
    assert (await failure(bogus)).error.code is ErrorCode.UNAUTHORIZED


async def test_leaving_while_waiting_withdraws_the_request(room: Session) -> None:
    owner = await room.owner()
    jo = knock(room, "Jo")
    await owner.next(JoinRequested)
    await jo.stop()
    assert (await owner.next(JoinResolved)).decision is JoinDecision.GONE
    assert owner.client.projection.state.join_requests == {}


async def test_too_many_people_waiting_are_turned_away(tmp_path: Path) -> None:
    provider = FakeProvider([reply("ok")])
    async with running_session(
        tmp_path, relayed=False, provider=provider, overrides={"max_pending_joins": 1}
    ) as session:
        owner = await session.owner()
        first = knock(session, "One")
        await owner.next(JoinRequested)
        second = knock(session, "Two")
        error = await failure(second)
        assert "too many people are waiting" in error.error.message
        await first.next(JoinPending)
        assert len(owner.client.projection.state.join_requests) == 1


async def test_a_request_nobody_answers_expires(tmp_path: Path) -> None:
    provider = FakeProvider([reply("ok")])
    async with running_session(
        tmp_path, relayed=False, provider=provider, overrides={"join_timeout_s": KNOCK_TIMEOUT}
    ) as session:
        owner = await session.owner()
        late = knock(session, "Late")
        await owner.next(JoinRequested)
        error = await failure(late)
        assert "did not answer in time" in error.error.message
        assert (await owner.next(JoinResolved)).decision is JoinDecision.EXPIRED
        assert owner.client.projection.state.join_requests == {}


async def test_a_full_room_turns_the_approved_away(tmp_path: Path) -> None:
    provider = FakeProvider([reply("ok")])
    async with running_session(
        tmp_path, relayed=False, provider=provider, overrides={"max_participants": 2}
    ) as session:
        owner = await session.owner()
        alia = knock(session, "Alia")
        asked = await owner.next(JoinRequested)
        await owner.client.send(JoinDecide(request_id=asked.request.id, decision="allow"))
        await alia.next(SessionWelcome)
        bek = knock(session, "Bek")
        second = await owner.next(JoinRequested)
        await owner.client.send(JoinDecide(request_id=second.request.id, decision="allow"))
        assert "the room is full" in (await failure(bek)).error.message


async def test_a_decision_about_a_request_that_is_gone_is_an_error(room: Session) -> None:
    owner = await room.owner()
    with pytest.raises(CommandRejected) as caught:
        await owner.client.send(JoinDecide(request_id="j_nope", decision="allow"))
    assert caught.value.error.code is ErrorCode.NOT_FOUND


async def host_again(tmp_path: Path, relay: RelayServer) -> Any:
    workspace = tmp_path / "ws"
    workspace.mkdir(exist_ok=True)
    settings = HostSettings(
        workspace=workspace,
        data_dir=tmp_path / "data",
        room=ROOM,
        port=free_port(),
        relay_url=relay.url,
        provider="fake",
    )
    return await build_host(settings, provider=FakeProvider([reply("ok")]))


async def test_the_room_link_survives_a_restart_and_waiting_requests_do_not(tmp_path: Path) -> None:
    relay = RelayServer()
    await relay.start()
    first = await host_again(tmp_path, relay)
    serving = asyncio.create_task(first.serve())
    session = Session(host=first, watchers=[], relay=relay)
    owner = await session.owner()
    link = first.room_link.link
    waiting = knock(session, "Kim", link=link)
    await owner.next(JoinRequested)

    serving.cancel()
    await asyncio.gather(serving, return_exceptions=True)
    for watcher in (owner, waiting):
        await watcher.stop()
    await first.close()

    second = await host_again(tmp_path, relay)
    try:
        assert second.room_link.link == link
        assert list(second.actor.state.join_requests) == []
        records = await second.store.read()
        decisions = [r.event.decision for r in records if isinstance(r.event, JoinResolved)]
        assert JoinDecision.EXPIRED in decisions
    finally:
        await second.close()
        await relay.stop()
