import asyncio
import json
import urllib.request
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass

import pytest
import uvicorn
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tests.e2e.support import free_port
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from plural.protocol.relay import RelayOpen
from plural.relay.app import create_app
from plural.relay.limits import PeerGate, RelayLimits
from plural.relay.rooms import CLOSE_RATE_LIMITED, CLOSE_ROOM_TAKEN
from plural.security.tokens import TokenSigner


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass(slots=True)
class Relay:
    url: str
    clock: Clock

    async def metrics(self) -> dict[str, int]:
        def fetch() -> dict[str, int]:
            with urllib.request.urlopen(f"http://{self.url}/metrics", timeout=5) as response:
                return json.load(response)

        return await asyncio.to_thread(fetch)

    async def host(
        self, room: str, signer: TokenSigner | None = None, *, forwarded: str | None = None
    ) -> ClientConnection:
        signer = signer or TokenSigner(Ed25519PrivateKey.generate())
        headers = {"X-Forwarded-For": forwarded} if forwarded else None
        socket = await connect(f"ws://{self.url}/host/{room}", additional_headers=headers)
        opening = RelayOpen(
            room=room,
            public_key=signer.verifier.public_b64(),
            proof=signer.prove(room.encode()),
        )
        with suppress(ConnectionClosed):
            await socket.send(opening.model_dump_json())
        return socket

    async def guest(self, room: str) -> ClientConnection:
        return await connect(f"ws://{self.url}/{room}")


@asynccontextmanager
async def running_relay(limits: RelayLimits, *, proxy_hops: int = 0) -> AsyncGenerator[Relay]:
    clock = Clock()
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(limits, proxy_hops=proxy_hops, clock=clock),
            host="127.0.0.1",
            port=port,
            log_level="warning",
            proxy_headers=False,
        )
    )
    task = asyncio.create_task(server.serve())
    async with asyncio.timeout(10):
        while not server.started:
            await asyncio.sleep(0.01)
    try:
        yield Relay(f"127.0.0.1:{port}", clock)
    finally:
        server.should_exit = True
        await task


async def closed_with(socket: ClientConnection, timeout: float = 5) -> int | None:
    with suppress(TimeoutError):
        async with asyncio.timeout(timeout):
            with pytest.raises(ConnectionClosed) as caught:
                await socket.recv()
            received = caught.value.rcvd
            return received.code if received else None
    return None


async def alive(socket: ClientConnection) -> bool:
    try:
        async with asyncio.timeout(0.3):
            await socket.recv()
    except TimeoutError:
        return True
    except ConnectionClosed:
        return False
    return True


async def settle(relay: Relay, rooms: int) -> None:
    async with asyncio.timeout(5):
        while (await relay.metrics())["rooms"] != rooms:
            await asyncio.sleep(0.02)


async def test_a_room_is_forgotten_when_its_host_has_been_gone_for_the_ttl() -> None:
    async with running_relay(RelayLimits(room_ttl_s=60)) as relay:
        host = await relay.host("r_a")
        await settle(relay, 1)
        await host.close()
        await asyncio.sleep(0.2)
        assert (await relay.metrics())["rooms"] == 1
        relay.clock.advance(59)
        assert (await relay.metrics())["rooms"] == 1
        relay.clock.advance(2)
        assert (await relay.metrics())["rooms"] == 0


async def test_a_host_that_comes_back_keeps_its_room_and_its_key() -> None:
    signer = TokenSigner(Ed25519PrivateKey.generate())
    async with running_relay(RelayLimits(room_ttl_s=60)) as relay:
        first = await relay.host("r_a", signer)
        await settle(relay, 1)
        await first.close()
        await asyncio.sleep(0.2)
        relay.clock.advance(30)
        again = await relay.host("r_a", signer)
        assert await alive(again)
        relay.clock.advance(120)
        assert (await relay.metrics())["rooms"] == 1


async def test_another_key_cannot_take_a_room_during_the_ttl_but_can_after_it() -> None:
    async with running_relay(RelayLimits(room_ttl_s=60)) as relay:
        owner = await relay.host("r_a")
        await settle(relay, 1)
        await owner.close()
        await asyncio.sleep(0.2)
        intruder = await relay.host("r_a")
        assert await closed_with(intruder) == CLOSE_ROOM_TAKEN
        relay.clock.advance(61)
        successor = await relay.host("r_a")
        assert await alive(successor)


async def test_rooms_freed_by_the_ttl_make_room_for_new_ones() -> None:
    async with running_relay(
        RelayLimits(room_ttl_s=60, max_rooms=2, max_rooms_per_peer=10)
    ) as relay:
        first = await relay.host("r_1")
        second = await relay.host("r_2")
        await settle(relay, 2)
        refused = await relay.host("r_3")
        assert await closed_with(refused) == CLOSE_RATE_LIMITED
        await first.close()
        await second.close()
        await asyncio.sleep(0.2)
        relay.clock.advance(61)
        assert await alive(await relay.host("r_3"))


async def test_one_address_cannot_hold_more_rooms_than_the_limit() -> None:
    async with running_relay(RelayLimits(max_rooms_per_peer=2)) as relay:
        first = await relay.host("r_1")
        second = await relay.host("r_2")
        third = await relay.host("r_3")
        assert await closed_with(third) == CLOSE_RATE_LIMITED
        assert await alive(first)
        assert await alive(second)
        await first.close()
        await asyncio.sleep(0.2)
        assert await alive(await relay.host("r_4"))


async def test_one_address_cannot_hold_more_guests_than_the_limit() -> None:
    async with running_relay(RelayLimits(max_guests_per_peer=2)) as relay:
        host = await relay.host("r_1")
        await settle(relay, 1)
        guests = [await relay.guest("r_1") for _ in range(2)]
        refused = await relay.guest("r_1")
        assert await closed_with(refused) == CLOSE_RATE_LIMITED
        assert await alive(guests[0])
        assert await alive(host)


async def test_a_flood_of_connections_from_one_address_is_slowed() -> None:
    limits = RelayLimits(connect_burst=3, connects_per_second=0.001, max_guests_per_peer=100)
    async with running_relay(limits) as relay:
        host = await relay.host("r_1")
        sockets = [await relay.guest("r_1") for _ in range(2)]
        refused = await relay.guest("r_1")
        assert await closed_with(refused) == CLOSE_RATE_LIMITED
        assert await alive(host)
        assert await alive(sockets[0])


async def test_a_proxy_header_tells_clients_apart_only_when_proxies_are_configured() -> None:
    async with running_relay(RelayLimits(max_rooms_per_peer=1), proxy_hops=1) as relay:
        first = await relay.host("r_1", forwarded="203.0.113.1")
        second = await relay.host("r_2", forwarded="203.0.113.2")
        spoofed = await relay.host("r_3", forwarded="198.51.100.9, 203.0.113.1")
        assert await alive(first)
        assert await alive(second)
        assert await closed_with(spoofed) == CLOSE_RATE_LIMITED

    async with running_relay(RelayLimits(max_rooms_per_peer=1), proxy_hops=0) as relay:
        first = await relay.host("r_1", forwarded="203.0.113.1")
        second = await relay.host("r_2", forwarded="203.0.113.2")
        assert await alive(first)
        assert await closed_with(second) == CLOSE_RATE_LIMITED


def test_idle_addresses_are_forgotten() -> None:
    clock = Clock()
    gate = PeerGate(RelayLimits(connect_burst=1000), clock)
    for index in range(1500):
        assert gate.admit(f"10.0.{index // 250}.{index % 250}", host=False)
        gate.release(f"10.0.{index // 250}.{index % 250}", host=False)
        clock.advance(10)
    assert len(gate._peers) < 1100  # pyright: ignore[reportPrivateUsage]
