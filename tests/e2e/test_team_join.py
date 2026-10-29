import asyncio
import secrets
import time
from collections.abc import AsyncGenerator
from contextlib import suppress
from pathlib import Path

import pytest

from plural.agent.providers.fake import FakeProvider, reply
from plural.client.connection import CommandRejected
from plural.client.reconnect import JoinLink, SessionClient
from plural.host.bootstrap import Host, build_host
from plural.host.config import HostSettings
from plural.host.team import create_team
from plural.protocol.commands import ParticipantRevoke, PromptSubmit, TeamProof
from plural.protocol.envelope import ErrorCode
from plural.protocol.events import ParticipantJoined, ParticipantRevoked, SessionSnapshot
from plural.protocol.models import Role
from plural.security.identity import Identity, build_team_proof
from tests.e2e.support import CLIENT, RelayServer, Watcher, free_port, refusal
from tests.e2e.team_support import Member, two_members

ROOM = "r_team"


@pytest.fixture
async def relay(tmp_path: Path) -> AsyncGenerator[RelayServer]:
    server = RelayServer(teams=tmp_path / "relay" / "teams.db")
    await server.start()
    yield server
    await server.stop()


def prover(member: Member):
    profile = member.store.load()
    assert profile is not None
    identity = member.store.identity()

    def make(room: str) -> TeamProof:
        return build_team_proof(
            identity,
            profile.certificate,
            room,
            timestamp=int(time.time()),
            nonce=secrets.token_hex(8),
        )

    return make


def visit(relay: RelayServer, member: Member, name: str | None = None) -> SessionClient:
    return SessionClient(
        JoinLink.parse(f"{relay.url}/{ROOM}"),
        name=name or member.name,
        client=CLIENT,
        team=prover(member),
    )


async def hosting(
    relay: RelayServer, owner: Member, tmp_path: Path, *, team: bool = True, ttl: float = 30
) -> tuple[Host, asyncio.Task[None]]:
    workspace = tmp_path / "ws"
    workspace.mkdir(exist_ok=True)
    settings = HostSettings(
        workspace=workspace,
        data_dir=owner.root / "data",
        room=ROOM,
        port=free_port(),
        relay_url=relay.url,
        provider="fake",
        team=team,
        team_roster_ttl_s=ttl,
    )
    host = await build_host(settings, provider=FakeProvider([reply("ok")]))
    return host, asyncio.create_task(host.serve())


async def stop(host: Host, serving: asyncio.Task[None], *watchers: Watcher) -> None:
    for watcher in watchers:
        await watcher.stop()
    serving.cancel()
    with suppress(asyncio.CancelledError):
        await serving
    await host.close()


async def test_a_team_member_walks_into_a_team_session_as_a_viewer(
    relay: RelayServer, tmp_path: Path
) -> None:
    vlad, alia = await two_members(relay, tmp_path)
    host, serving = await hosting(relay, vlad, tmp_path)
    owner = Watcher(SessionClient(JoinLink.parse(host.host_link), name="vlad", client=CLIENT))
    watcher = Watcher(visit(relay, alia))
    try:
        await watcher.next(SessionSnapshot)
        me = watcher.client.projection.me
        assert me is not None
        assert (me.name, me.role) == ("alia", Role.VIEWER)
        joined = await owner.next(ParticipantJoined)
        assert (joined.participant.name, joined.participant.role) == ("alia", Role.VIEWER)
        assert joined.participant.id.startswith("p_team_")
    finally:
        await stop(host, serving, owner, watcher)


async def test_a_team_viewer_can_read_but_not_prompt(relay: RelayServer, tmp_path: Path) -> None:
    vlad, alia = await two_members(relay, tmp_path)
    host, serving = await hosting(relay, vlad, tmp_path)
    watcher = Watcher(visit(relay, alia))
    try:
        await watcher.next(SessionSnapshot)
        with pytest.raises(CommandRejected) as caught:
            await watcher.client.send(PromptSubmit(text="hello"))
        assert caught.value.error.code is ErrorCode.FORBIDDEN
    finally:
        await stop(host, serving, watcher)


async def test_coming_back_keeps_the_same_seat(relay: RelayServer, tmp_path: Path) -> None:
    vlad, alia = await two_members(relay, tmp_path)
    host, serving = await hosting(relay, vlad, tmp_path)
    first = Watcher(visit(relay, alia))
    await first.next(SessionSnapshot)
    first_id = first.client.projection.me_id
    await first.stop()
    second = Watcher(visit(relay, alia))
    try:
        await second.next(SessionSnapshot)
        assert second.client.projection.me_id == first_id
        assert len(host.actor.state.participants) == 2
    finally:
        await stop(host, serving, second)


async def test_a_session_that_is_not_shared_with_a_team_refuses_team_members(
    relay: RelayServer, tmp_path: Path
) -> None:
    vlad, alia = await two_members(relay, tmp_path)
    host, serving = await hosting(relay, vlad, tmp_path, team=False)
    try:
        assert await refusal(visit(relay, alia)) is ErrorCode.FORBIDDEN
    finally:
        await stop(host, serving)


async def test_someone_from_another_team_is_refused(relay: RelayServer, tmp_path: Path) -> None:
    vlad, _ = await two_members(relay, tmp_path)
    outsider = Member(tmp_path, "mallory")
    outsider.store.save(
        await create_team(relay.url, outsider.store.identity(), team="Other", member="mallory")
    )
    host, serving = await hosting(relay, vlad, tmp_path)
    try:
        assert await refusal(visit(relay, outsider)) is ErrorCode.UNAUTHORIZED
    finally:
        await stop(host, serving)


async def test_a_stolen_certificate_without_its_key_is_refused(
    relay: RelayServer, tmp_path: Path
) -> None:
    vlad, alia = await two_members(relay, tmp_path)
    profile = alia.store.load()
    assert profile is not None
    thief = Identity.load_or_create(tmp_path / "thief.pem")
    client = SessionClient(
        JoinLink.parse(f"{relay.url}/{ROOM}"),
        name="alia",
        client=CLIENT,
        team=lambda room: build_team_proof(
            thief, profile.certificate, room, timestamp=int(time.time()), nonce=secrets.token_hex(8)
        ),
    )
    host, serving = await hosting(relay, vlad, tmp_path)
    try:
        assert await refusal(client) is ErrorCode.UNAUTHORIZED
    finally:
        await stop(host, serving)


async def test_a_kicked_team_member_cannot_walk_back_in(relay: RelayServer, tmp_path: Path) -> None:
    vlad, alia = await two_members(relay, tmp_path)
    host, serving = await hosting(relay, vlad, tmp_path)
    owner = Watcher(SessionClient(JoinLink.parse(host.host_link), name="vlad", client=CLIENT))
    watcher = Watcher(visit(relay, alia))
    try:
        await watcher.next(SessionSnapshot)
        alia_id = watcher.client.projection.me_id
        assert alia_id is not None
        await owner.client.send(ParticipantRevoke(participant_id=alia_id))
        await owner.next(ParticipantRevoked)
        assert await refusal(visit(relay, alia)) is ErrorCode.FORBIDDEN
        assert await host.store.meta("team_banned") == f'["{alia.store.identity().member_id}"]'
    finally:
        await stop(host, serving, owner, watcher)


async def test_a_member_the_team_removed_loses_the_seat_they_already_held(
    relay: RelayServer, tmp_path: Path
) -> None:
    vlad, alia = await two_members(relay, tmp_path)
    host, serving = await hosting(relay, vlad, tmp_path, ttl=0.1)
    watcher = Watcher(visit(relay, alia))
    try:
        await watcher.next(SessionSnapshot)
        await (await vlad.client()).remove("alia")
        await watcher.stop()
        await asyncio.sleep(0.2)
        again = visit(relay, alia)
        again._token = watcher.client._token  # pyright: ignore[reportPrivateUsage]
        assert await refusal(again) is ErrorCode.UNAUTHORIZED
    finally:
        await stop(host, serving)


async def test_a_team_viewer_who_arrives_late_gets_the_whole_conversation(
    relay: RelayServer, tmp_path: Path
) -> None:
    from plural.protocol.events import RunEnded

    vlad, alia = await two_members(relay, tmp_path)
    host, serving = await hosting(relay, vlad, tmp_path)
    owner = Watcher(SessionClient(JoinLink.parse(host.host_link), name="vlad", client=CLIENT))
    await owner.next(SessionSnapshot)
    await owner.client.send(PromptSubmit(text="say ok"))
    await owner.next(RunEnded)
    watcher = Watcher(visit(relay, alia))
    try:
        await watcher.next(SessionSnapshot)
        texts = [entry.text for entry in watcher.client.projection.state.transcript]
        assert "say ok" in texts
        assert "ok" in texts
    finally:
        await stop(host, serving, owner, watcher)


async def test_a_team_member_the_host_let_write_keeps_the_right_when_they_come_back(
    relay: RelayServer, tmp_path: Path
) -> None:
    from plural.protocol.commands import AccessDecide, AccessRequest
    from plural.protocol.events import AccessRequested, ParticipantRoleChanged

    vlad, alia = await two_members(relay, tmp_path)
    host, serving = await hosting(relay, vlad, tmp_path)
    owner = Watcher(SessionClient(JoinLink.parse(host.host_link), name="vlad", client=CLIENT))
    first = Watcher(visit(relay, alia))
    try:
        await first.next(SessionSnapshot)
        await first.client.send(AccessRequest(note="I can take the login bug"))
        asked = await owner.next(AccessRequested)
        assert asked.request.name == "alia"
        await owner.client.send(
            AccessDecide(participant_id=asked.request.participant_id, decision="allow")
        )
        changed = await first.next(ParticipantRoleChanged)
        assert changed.role is Role.PARTICIPANT
        await first.stop()

        second = Watcher(visit(relay, alia))
        try:
            await second.next(SessionSnapshot)
            me = second.client.projection.me
            assert me is not None
            assert me.role is Role.PARTICIPANT
            await second.client.send(PromptSubmit(text="look at the login bug"))
        finally:
            await second.stop()
    finally:
        await stop(host, serving, owner, first)
