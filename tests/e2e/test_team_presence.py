import asyncio
from collections.abc import AsyncGenerator
from contextlib import suppress
from pathlib import Path

import pytest
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import ConnectionClosed, InvalidStatus

from plural.agent.providers.fake import FakeProvider, reply
from plural.client.reconnect import JoinLink, SessionClient
from plural.host import team_presence
from plural.host.bootstrap import build_host
from plural.host.config import HostSettings
from plural.host.team import TeamError, TeamStore
from plural.host.team_presence import TeamPresence, ensure_ready
from plural.protocol.models import Role
from plural.protocol.team import CardDraft, Endpoint, EndpointKind, PresenceCard, SessionStatus
from tests.e2e.support import CLIENT, RelayServer, Session, Watcher, free_port
from tests.e2e.team_support import Member, connect_as, two_members


@pytest.fixture
async def relay(tmp_path: Path) -> AsyncGenerator[RelayServer]:
    server = RelayServer(teams=tmp_path / "relay" / "teams.db")
    await server.start()
    yield server
    await server.stop()


def draft(room: str = "r_x", repo: str = "api") -> CardDraft:
    return CardDraft(
        room=room,
        repo=repo,
        branch="main",
        status=SessionStatus.IDLE,
        endpoints=(Endpoint(kind=EndpointKind.RELAY, url=f"wss://relay.example/{room}"),),
    )


async def listed(member: Member, until: int = 1, timeout: float = 5) -> list[str]:
    client = await member.client()
    async with asyncio.timeout(timeout):
        while True:
            names = [f"{card.owner}:{card.room}" for card in (await client.sessions()).sessions]
            if len(names) >= until:
                return names
            await asyncio.sleep(0.05)


async def _until_closed(socket: ClientConnection) -> None:
    while True:
        await socket.recv()


async def test_a_card_a_member_publishes_is_listed_for_the_team_with_the_owner_stamped(
    relay: RelayServer, tmp_path: Path
) -> None:
    vlad, alia = await two_members(relay, tmp_path)
    async with connect_as(vlad, relay) as socket:
        await socket.send(PresenceCard(card=draft()).model_dump_json())
        assert await listed(alia) == ["vlad:r_x"]
        (card,) = (await (await alia.client()).sessions()).sessions
        assert (card.repo, card.branch, card.status) == ("api", "main", SessionStatus.IDLE)
    assert await _gone(alia)


async def _gone(member: Member) -> bool:
    client = await member.client()
    async with asyncio.timeout(5):
        while (await client.sessions()).sessions:
            await asyncio.sleep(0.05)
    return True


async def test_a_stranger_cannot_list_or_publish(relay: RelayServer, tmp_path: Path) -> None:
    vlad, _ = await two_members(relay, tmp_path)
    mallory = Member(tmp_path, "mallory")
    mallory.store.save(vlad.store.load())  # type: ignore[arg-type]
    with pytest.raises(TeamError, match="not a member"):
        await (await mallory.client()).sessions()
    with pytest.raises(InvalidStatus):
        async with connect_as(mallory, relay):
            pass


async def test_a_member_cannot_take_over_another_members_room(
    relay: RelayServer, tmp_path: Path
) -> None:
    vlad, alia = await two_members(relay, tmp_path)
    async with connect_as(vlad, relay) as first:
        await first.send(PresenceCard(card=draft("r_x", "api")).model_dump_json())
        await listed(alia)
        async with connect_as(alia, relay) as second:
            await second.send(PresenceCard(card=draft("r_x", "evil")).model_dump_json())
            with pytest.raises(ConnectionClosed) as closed:
                await second.recv()
            assert closed.value.rcvd is not None
            assert closed.value.rcvd.code == 4429
        (card,) = (await (await alia.client()).sessions()).sessions
        assert (card.owner, card.repo) == ("vlad", "api")


async def test_garbage_and_oversized_frames_close_the_connection(
    relay: RelayServer, tmp_path: Path
) -> None:
    vlad, _ = await two_members(relay, tmp_path)
    for frame in ["not json", '{"type":"card","card":{"room":"r"}}', "x" * 9000]:
        async with connect_as(vlad, relay) as socket:
            await socket.send(frame)
            with pytest.raises(ConnectionClosed) as closed:
                await socket.recv()
            assert closed.value.rcvd is not None
            assert closed.value.rcvd.code == 4400


async def test_a_removed_member_loses_their_card_at_once(
    relay: RelayServer, tmp_path: Path
) -> None:
    vlad, alia = await two_members(relay, tmp_path)
    async with connect_as(alia, relay) as socket:
        await socket.send(PresenceCard(card=draft()).model_dump_json())
        await listed(vlad)
        await (await vlad.client()).remove("alia")
        assert await _gone(vlad)
        await socket.send(PresenceCard(card=draft()).model_dump_json())
        with pytest.raises(ConnectionClosed) as closed:
            await _until_closed(socket)
        assert closed.value.rcvd is not None
        assert closed.value.rcvd.code == 4401


async def test_a_running_host_shows_its_session_and_who_watches(
    relay: RelayServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(team_presence, "POLL_S", 0.05)
    vlad, alia = await two_members(relay, tmp_path)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    settings = HostSettings(
        workspace=workspace,
        data_dir=vlad.root / "data",
        room="r_live",
        port=free_port(),
        relay_url=relay.url,
        provider="fake",
        title="fix login",
        team=True,
    )
    ensure_ready(settings, vlad.store)
    host = await build_host(settings, provider=FakeProvider([reply("ok")]))
    serving = asyncio.create_task(host.serve())
    presence = asyncio.create_task(TeamPresence(host, settings, vlad.store).run())
    session = Session(host=host, watchers=[], relay=relay)
    try:
        assert await listed(alia) == ["vlad:r_live"]
        (card,) = (await (await alia.client()).sessions()).sessions
        assert (card.repo, card.title, card.viewers) == ("ws", "fix login", 0)
        assert card.endpoints[0].url == f"{relay.url}/r_live"

        watcher = Watcher(
            SessionClient(
                JoinLink.parse(host.invites.create(Role.VIEWER, 600).link),
                name="Alia",
                client=CLIENT,
            )
        )
        session.watchers.append(watcher)
        client = await alia.client()
        async with asyncio.timeout(5):
            while (await client.sessions()).sessions[0].viewers != 1:
                await asyncio.sleep(0.05)
    finally:
        for watcher in session.watchers:
            await watcher.stop()
        presence.cancel()
        serving.cancel()
        for task in (presence, serving):
            with suppress(asyncio.CancelledError):
                await task
        await host.close()
    assert await _gone(alia)


async def test_a_team_session_must_be_reachable_and_in_a_team(tmp_path: Path) -> None:
    store = TeamStore(tmp_path / "data")
    settings = HostSettings(workspace=tmp_path, data_dir=tmp_path / "data", team=True)
    with pytest.raises(team_presence.PresenceUnavailable, match="not in a team"):
        ensure_ready(settings, store)


async def test_the_ls_command_lists_live_sessions(
    relay: RelayServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from typer.testing import CliRunner

    from plural.cli.main import app

    vlad, alia = await two_members(relay, tmp_path)
    runner = CliRunner()

    async def run(member: Member, *args: str) -> str:
        monkeypatch.setenv("PLURAL_DATA_DIR", str(member.root / "data"))
        result = await asyncio.to_thread(runner.invoke, app, list(args))
        assert result.exit_code == 0, result.output
        return result.output

    assert "Nobody in Backend" in await run(alia, "ls")
    async with connect_as(vlad, relay) as socket:
        await socket.send(PresenceCard(card=draft("r_x", "api")).model_dump_json())
        await listed(alia)
        table = await run(alia, "ls")
        assert "vlad" in table
        assert "api · main" in table
        assert "idle" in table
        rows = json.loads(await run(alia, "ls", "--json"))
        assert [(row["owner"], row["repo"], row["room"]) for row in rows] == [
            ("vlad", "api", "r_x")
        ]
        assert "(you)" in await run(vlad, "ls")
