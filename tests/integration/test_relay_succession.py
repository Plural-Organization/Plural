"""A host hands its room to another key: the relay believes only the room's own key."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
import uvicorn
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tests.e2e.support import free_port
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from plural.protocol.capability import SuccessionClaims
from plural.protocol.relay import RelayOpen
from plural.relay.app import create_app
from plural.relay.rooms import CLOSE_HANDED_OVER, CLOSE_HOST_CHANGED, CLOSE_ROOM_TAKEN
from plural.security.succession import STATEMENT_TTL, sign_succession
from plural.security.tokens import TokenSigner

ROOM = "r_handover"


@asynccontextmanager
async def relay() -> AsyncGenerator[str]:
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    task = asyncio.create_task(server.serve())
    async with asyncio.timeout(10):
        while not server.started:
            await asyncio.sleep(0.01)
    try:
        yield f"ws://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


def key() -> TokenSigner:
    return TokenSigner(Ed25519PrivateKey.generate())


async def open_host(
    url: str, signer: TokenSigner, *, succession: str | None = None
) -> ClientConnection:
    socket = await connect(f"{url}/host/{ROOM}")
    opening = RelayOpen(
        room=ROOM,
        public_key=signer.verifier.public_b64(),
        proof=signer.prove(ROOM.encode()),
        succession=succession,
    )
    await socket.send(opening.model_dump_json())
    return socket


def word(old: TokenSigner, new: TokenSigner, *, ttl: timedelta = STATEMENT_TTL) -> str:
    now = datetime.now(UTC)
    claims = SuccessionClaims(
        room=ROOM,
        from_key=old.verifier.public_b64(),
        to_key=new.verifier.public_b64(),
        last_seq=7,
        iat=now,
        exp=now + ttl,
    )
    return sign_succession(old, claims)


async def closed_with(socket: ClientConnection) -> int:
    with pytest.raises(ConnectionClosed) as closed:
        async with asyncio.timeout(5):
            await socket.recv()
    assert closed.value.rcvd is not None
    return closed.value.rcvd.code


async def test_another_key_cannot_take_a_room_without_the_hosts_word() -> None:
    old, thief = key(), key()
    async with relay() as url:
        host = await open_host(url, old)
        await asyncio.sleep(0.2)
        taker = await open_host(url, thief)
        assert await closed_with(taker) == CLOSE_ROOM_TAKEN
        forged = await open_host(url, thief, succession=word(thief, thief))
        assert await closed_with(forged) == CLOSE_ROOM_TAKEN
        await host.close()


async def test_a_word_for_someone_else_or_a_lapsed_one_is_not_enough() -> None:
    old, new, other = key(), key(), key()
    async with relay() as url:
        host = await open_host(url, old)
        await asyncio.sleep(0.2)
        for succession in (word(old, other), word(old, new, ttl=timedelta(seconds=-1))):
            taker = await open_host(url, new, succession=succession)
            assert await closed_with(taker) == CLOSE_ROOM_TAKEN
        await host.close()


async def test_the_hosts_word_gives_the_room_to_the_new_key_and_guests_come_back() -> None:
    old, new = key(), key()
    async with relay() as url:
        host = await open_host(url, old)
        await asyncio.sleep(0.2)
        guest = await connect(f"{url}/{ROOM}")
        await asyncio.sleep(0.2)

        successor = await open_host(url, new, succession=word(old, new))
        assert await closed_with(host) == CLOSE_HANDED_OVER
        assert await closed_with(guest) == CLOSE_HOST_CHANGED

        # The room is the new key's now: the old key cannot come back, the new one can.
        back = await open_host(url, old)
        assert await closed_with(back) == CLOSE_ROOM_TAKEN
        await successor.close()
        again = await open_host(url, new)
        await asyncio.sleep(0.2)
        assert again.state.name == "OPEN"
        await again.close()
