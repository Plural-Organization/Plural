import asyncio
import json
import urllib.request
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import uvicorn
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tests.e2e.support import free_port
from websockets.asyncio.client import ClientConnection, connect

from plural.protocol.entitlement import EntitlementClaims
from plural.protocol.relay import RelayOpen
from plural.relay.app import create_app
from plural.relay.entitlements import EntitlementWatch
from plural.security.entitlement import EntitlementVerifier
from plural.security.tokens import TokenSigner, b64encode


@asynccontextmanager
async def relay_watching(
    accounts: Ed25519PrivateKey,
) -> AsyncGenerator[tuple[str, EntitlementWatch]]:
    watch = EntitlementWatch(
        "https://accounts.example",
        fetch=lambda _: EntitlementVerifier(accounts.public_key()),
    )
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(entitlements=watch), host="127.0.0.1", port=port, log_level="warning"
        )
    )
    task = asyncio.create_task(server.serve())
    async with asyncio.timeout(10):
        while not (server.started and watch.ready):
            await asyncio.sleep(0.01)
    try:
        yield f"127.0.0.1:{port}", watch
    finally:
        server.should_exit = True
        await task


def certificate(accounts: Ed25519PrivateKey, host_key: str) -> str:
    now = datetime.now(UTC)
    claims = EntitlementClaims(account="a_1", key=host_key, iat=now, exp=now + timedelta(days=14))
    body = claims.model_dump_json().encode()
    return f"{b64encode(body)}.{b64encode(accounts.sign(body))}"


async def open_room(
    url: str, room: str, entitlement: str | None, host: TokenSigner
) -> ClientConnection:
    socket = await connect(f"ws://{url}/host/{room}")
    opening = RelayOpen(
        room=room,
        public_key=host.verifier.public_b64(),
        proof=host.prove(room.encode()),
        entitlement=entitlement,
    )
    await socket.send(opening.model_dump_json())
    return socket


async def metrics(url: str) -> dict[str, object]:
    def fetch() -> dict[str, object]:
        with urllib.request.urlopen(f"http://{url}/metrics", timeout=5) as response:
            return json.load(response)

    return await asyncio.to_thread(fetch)


async def rooms_open(url: str, count: int) -> None:
    async with asyncio.timeout(5):
        while (await metrics(url))["rooms"] != count:
            await asyncio.sleep(0.02)


async def test_every_host_gets_a_room_and_the_relay_counts_what_it_found() -> None:
    accounts = Ed25519PrivateKey.generate()
    async with relay_watching(accounts) as (url, _):
        sockets: list[ClientConnection] = []
        try:
            signed_in = TokenSigner(Ed25519PrivateKey.generate())
            sockets.append(
                await open_room(
                    url,
                    "r_signed",
                    certificate(accounts, signed_in.verifier.public_b64()),
                    signed_in,
                )
            )
            sockets.append(
                await open_room(url, "r_guest", None, TokenSigner(Ed25519PrivateKey.generate()))
            )
            stranger = TokenSigner(Ed25519PrivateKey.generate())
            forged = certificate(Ed25519PrivateKey.generate(), stranger.verifier.public_b64())
            sockets.append(await open_room(url, "r_forged", forged, stranger))
            await rooms_open(url, 3)
            counts = (await metrics(url))["entitlements"]
            assert counts == {"valid": 1, "none": 1, "forged": 1}
        finally:
            for socket in sockets:
                await socket.close()


async def test_a_relay_without_an_accounts_service_reports_nothing_extra() -> None:
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    task = asyncio.create_task(server.serve())
    async with asyncio.timeout(10):
        while not server.started:
            await asyncio.sleep(0.01)
    try:
        assert set(await metrics(f"127.0.0.1:{port}")) == {"rooms", "guests"}
    finally:
        server.should_exit = True
        await task
