import asyncio
from pathlib import Path

from websockets.exceptions import ConnectionClosed

from plural.agent.providers.fake import FakeProvider, reply
from plural.client.reconnect import JoinLink, SessionClient
from plural.host.bootstrap import build_host
from plural.host.config import HostSettings
from plural.protocol.commands import TypingSet
from plural.protocol.events import ParticipantTyping
from tests.e2e.support import (
    CLIENT,
    ROOM,
    RelayServer,
    Session,
    Watcher,
    free_port,
    running_session,
)

OUTAGE_S = 1.0


async def talk_until_heard(speaker: Watcher, listener: Watcher, timeout: float = 30) -> None:
    async with asyncio.timeout(timeout):
        while True:
            try:
                await speaker.client.send(TypingSet(typing=True))
                await listener.next(ParticipantTyping, timeout=1.0)
                return
            except (ConnectionError, ConnectionClosed, TimeoutError, OSError):
                await asyncio.sleep(0.1)


async def test_guests_and_the_host_come_back_after_the_relay_restarts(tmp_path: Path) -> None:
    provider = FakeProvider([reply("ok")])
    async with running_session(tmp_path, relayed=True, provider=provider) as session:
        relay = session.relay
        assert relay is not None
        owner = await session.owner()
        guest = await session.guest("Alia")
        before = guest.client.projection.me_id
        await talk_until_heard(guest, owner)

        await relay.stop()
        await asyncio.sleep(OUTAGE_S)
        assert not guest._task.done()  # pyright: ignore[reportPrivateUsage]
        assert not owner._task.done()  # pyright: ignore[reportPrivateUsage]
        await relay.start()

        await talk_until_heard(guest, owner)
        assert guest.client.projection.me_id == before
        assert not guest._task.done()  # pyright: ignore[reportPrivateUsage]


async def test_the_relay_can_be_down_for_longer_than_a_blip(tmp_path: Path) -> None:
    provider = FakeProvider([reply("ok")])
    async with running_session(tmp_path, relayed=True, provider=provider) as session:
        relay = session.relay
        assert relay is not None
        owner = await session.owner()
        guest = await session.guest("Alia")
        await relay.stop()
        await asyncio.sleep(8)
        await relay.start()
        await talk_until_heard(guest, owner, timeout=40)


async def test_a_restarted_host_takes_its_room_back_and_guests_keep_their_seat(
    tmp_path: Path,
) -> None:
    relay = RelayServer()
    await relay.start()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    settings = HostSettings(
        workspace=workspace,
        data_dir=tmp_path / "data",
        room=ROOM,
        port=free_port(),
        relay_url=relay.url,
        provider="fake",
    )
    first = await build_host(settings, provider=FakeProvider([reply("ok")]))
    serving = asyncio.create_task(first.serve())
    session = Session(host=first, watchers=[], relay=relay)
    owner = await session.owner()
    guest = await session.guest("Alia")
    seat = guest.client.projection.me_id
    await talk_until_heard(guest, owner)

    serving.cancel()
    await asyncio.gather(serving, return_exceptions=True)
    await first.close()
    await asyncio.sleep(OUTAGE_S)
    assert not guest._task.done()  # pyright: ignore[reportPrivateUsage]

    second = await build_host(settings, provider=FakeProvider([reply("ok")]))
    serving = asyncio.create_task(second.serve())
    try:
        again = Watcher(SessionClient(JoinLink.parse(second.host_link), name="Host", client=CLIENT))
        session.watchers.append(again)
        await talk_until_heard(guest, again)
        assert guest.client.projection.me_id == seat
    finally:
        for watcher in session.watchers:
            await watcher.stop()
        serving.cancel()
        await asyncio.gather(serving, return_exceptions=True)
        await second.close()
        await relay.stop()
