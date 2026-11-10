import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from websockets.asyncio.server import ServerConnection, serve

from plural.host.chat_import import label
from plural.host.mcp_link import McpLink, import_address, load_or_create_secret


class Gateway:
    """A stand-in for the MCP gateway: it takes a host's hello, then puts offers to it."""

    def __init__(self) -> None:
        self.hellos: list[dict[str, Any]] = []
        self.sockets: list[ServerConnection] = []
        self.connected = asyncio.Event()

    async def handler(self, socket: ServerConnection) -> None:
        self.hellos.append(json.loads(await socket.recv()))
        self.sockets.append(socket)
        self.connected.set()
        await socket.wait_closed()

    async def ask(self, **offer: Any) -> dict[str, Any]:
        await self.sockets[-1].send(json.dumps({"type": "offer", "id": "o1", **offer}))
        return json.loads(await asyncio.wait_for(self.sockets[-1].recv(), 5))


@asynccontextmanager
async def gateway() -> AsyncGenerator[tuple[Gateway, str]]:
    fake = Gateway()
    async with serve(fake.handler, "127.0.0.1", 0) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        yield fake, f"http://127.0.0.1:{port}"


async def test_the_host_says_hello_with_its_secret_and_answers_an_offer() -> None:
    seen: list[tuple[str, str, str]] = []

    async def offer(source: str, title: str, text: str) -> bool:
        seen.append((source, title, text))
        return True

    async with gateway() as (fake, url):
        link = asyncio.create_task(McpLink(url, "s" * 32, offer).serve())
        try:
            await asyncio.wait_for(fake.connected.wait(), 5)
            assert fake.hellos == [{"type": "hello", "secret": "s" * 32}]
            answer = await fake.ask(source="Claude", title="Billing", context=" the note ")
        finally:
            link.cancel()
    assert answer == {"type": "answer", "id": "o1", "accepted": True}
    assert seen == [("Claude", "Billing", "the note")]


async def test_a_declined_empty_or_failing_offer_is_answered_no() -> None:
    async def decline(source: str, title: str, text: str) -> bool:
        return False

    async def fail(source: str, title: str, text: str) -> bool:
        raise RuntimeError("boom")

    for handler in (decline, fail):
        async with gateway() as (fake, url):
            link = asyncio.create_task(McpLink(url, "s" * 32, handler).serve())
            try:
                await asyncio.wait_for(fake.connected.wait(), 5)
                answer = await fake.ask(source="x", title="y", context="note")
            finally:
                link.cancel()
        assert answer["accepted"] is False
    async with gateway() as (fake, url):
        link = asyncio.create_task(McpLink(url, "s" * 32, decline).serve())
        try:
            await asyncio.wait_for(fake.connected.wait(), 5)
            empty = await fake.ask(context="  ")
        finally:
            link.cancel()
    assert empty["accepted"] is False


async def test_the_host_connects_again_when_the_gateway_drops_it() -> None:
    async def offer(source: str, title: str, text: str) -> bool:
        return True

    async with gateway() as (fake, url):
        link = asyncio.create_task(McpLink(url, "s" * 32, offer, max_delay_s=0.1).serve())
        try:
            await asyncio.wait_for(fake.connected.wait(), 5)
            fake.connected.clear()
            await fake.sockets[0].close()
            await asyncio.wait_for(fake.connected.wait(), 5)
        finally:
            link.cancel()
    assert len(fake.hellos) == 2


def test_the_secret_is_made_once_and_kept_private(tmp_path: Path) -> None:
    first = load_or_create_secret(tmp_path / "state")
    assert load_or_create_secret(tmp_path / "state") == first
    assert len(first) >= 20
    assert (tmp_path / "state" / "import_secret").stat().st_mode & 0o077 == 0


def test_the_address_is_the_gateway_over_http_with_the_secret() -> None:
    assert import_address("wss://mcp.example/", "abc") == "https://mcp.example/i/abc"
    assert import_address("http://127.0.0.1:8080", "abc") == "http://127.0.0.1:8080/i/abc"


def test_a_label_cannot_smuggle_markup_into_the_source() -> None:
    assert label("Claude", "Chat") == "Claude"
    assert "<" not in label("Claude <b>x</b>\nignore previous", "Chat")
    assert label("<<<>>>", "Chat") == "Chat"
