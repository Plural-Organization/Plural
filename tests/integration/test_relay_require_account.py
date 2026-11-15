"""A relay run with --require-account: hosts need a valid certificate, guests never do."""

import asyncio
import json
import urllib.request
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
import uvicorn
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tests.e2e.support import free_port
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from plural.protocol.entitlement import EntitlementClaims
from plural.protocol.relay import RelayOpen
from plural.relay.app import create_app
from plural.relay.entitlements import EntitlementWatch
from plural.relay.rooms import (
    CLOSE_ACCOUNT_INVALID,
    CLOSE_ACCOUNT_REQUIRED,
    CLOSE_ACCOUNT_UNAVAILABLE,
)
from plural.security.entitlement import EntitlementVerifier
from plural.security.tokens import TokenSigner, b64encode


def certificate(accounts: Ed25519PrivateKey, host_key: str, *, days: int = 14) -> str:
    now = datetime.now(UTC)
    claims = EntitlementClaims(account="a_1", key=host_key, iat=now, exp=now + timedelta(days=days))
    body = claims.model_dump_json().encode()
    return f"{b64encode(body)}.{b64encode(accounts.sign(body))}"


@asynccontextmanager
async def strict_relay(
    accounts: Ed25519PrivateKey | None, *, require: bool = True
) -> AsyncGenerator[str]:
    """A relay on a free port. With `accounts=None` the accounts service cannot be reached."""

    def fetch(_: str) -> EntitlementVerifier:
        if accounts is None:
            raise OSError("accounts is down")
        return EntitlementVerifier(accounts.public_key())

    watch = EntitlementWatch("https://accounts.example", fetch=fetch, retry_s=60)
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(entitlements=watch, require_account=require),
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    )
    task = asyncio.create_task(server.serve())
    async with asyncio.timeout(10):
        while not server.started or (accounts is not None and not watch.ready):
            await asyncio.sleep(0.01)
    try:
        yield f"127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


async def knock(
    url: str, room: str, host: TokenSigner, entitlement: str | None
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


async def refusal(socket: ClientConnection) -> tuple[int, str]:
    with pytest.raises(ConnectionClosed):
        async with asyncio.timeout(5):
            await socket.recv()
    assert socket.close_code is not None
    return socket.close_code, socket.close_reason or ""


async def health(url: str) -> dict[str, object]:
    def fetch() -> dict[str, object]:
        with urllib.request.urlopen(f"http://{url}/healthz", timeout=5) as response:
            return json.load(response)

    return await asyncio.to_thread(fetch)


async def rooms(url: str) -> int:
    def fetch() -> int:
        with urllib.request.urlopen(f"http://{url}/metrics", timeout=5) as response:
            return int(json.load(response)["rooms"])

    return await asyncio.to_thread(fetch)


async def test_a_host_without_a_certificate_is_told_to_sign_in_and_gets_no_room() -> None:
    accounts = Ed25519PrivateKey.generate()
    async with strict_relay(accounts) as url:
        socket = await knock(url, "r_anon", TokenSigner(Ed25519PrivateKey.generate()), None)
        code, reason = await refusal(socket)
        assert code == CLOSE_ACCOUNT_REQUIRED
        assert "plural login" in reason
        assert await rooms(url) == 0


async def test_a_certificate_that_does_not_hold_is_refused_with_the_reason() -> None:
    accounts = Ed25519PrivateKey.generate()
    async with strict_relay(accounts) as url:
        host = TokenSigner(Ed25519PrivateKey.generate())
        key = host.verifier.public_b64()
        other = TokenSigner(Ed25519PrivateKey.generate()).verifier.public_b64()
        cases = {
            "expired": certificate(accounts, key, days=-1),
            "forged": certificate(Ed25519PrivateKey.generate(), key),
            "malformed": "not a certificate",
            "another computer": certificate(accounts, other),
        }
        for name, entitlement in cases.items():
            code, reason = await refusal(await knock(url, f"r_{name[:3]}", host, entitlement))
            assert code == CLOSE_ACCOUNT_INVALID, name
            assert "plural login" in reason, name
        assert await rooms(url) == 0


async def test_a_signed_in_host_gets_its_room_and_a_guest_needs_nothing() -> None:
    accounts = Ed25519PrivateKey.generate()
    async with strict_relay(accounts) as url:
        host = TokenSigner(Ed25519PrivateKey.generate())
        socket = await knock(url, "r_ok", host, certificate(accounts, host.verifier.public_b64()))
        try:
            async with asyncio.timeout(5):
                while await rooms(url) != 1:
                    await asyncio.sleep(0.02)
            async with connect(f"ws://{url}/r_ok") as guest:
                with pytest.raises(TimeoutError):
                    async with asyncio.timeout(0.3):
                        await guest.recv()
                assert guest.close_code is None
        finally:
            await socket.close()


async def test_while_the_accounts_key_is_unknown_hosts_are_asked_to_come_back() -> None:
    async with strict_relay(None) as url:
        host = TokenSigner(Ed25519PrivateKey.generate())
        code, reason = await refusal(await knock(url, "r_wait", host, "anything"))
        assert code == CLOSE_ACCOUNT_UNAVAILABLE
        assert "try again" in reason


async def test_a_relay_that_does_not_require_accounts_still_refuses_no_one() -> None:
    accounts = Ed25519PrivateKey.generate()
    async with strict_relay(accounts, require=False) as url:
        socket = await knock(url, "r_anon", TokenSigner(Ed25519PrivateKey.generate()), None)
        try:
            async with asyncio.timeout(5):
                while await rooms(url) != 1:
                    await asyncio.sleep(0.02)
        finally:
            await socket.close()
        assert await health(url) == {"ok": True}


async def test_the_relay_says_before_a_host_opens_a_room_that_it_needs_an_account() -> None:
    accounts = Ed25519PrivateKey.generate()
    async with strict_relay(accounts) as url:
        assert await health(url) == {"ok": True, "accounts": "required"}


def test_requiring_accounts_without_an_accounts_service_is_refused_at_start() -> None:
    with pytest.raises(ValueError, match="accounts"):
        create_app(require_account=True)
