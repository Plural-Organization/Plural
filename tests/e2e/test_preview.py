import asyncio
import http.client
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import pytest

from plural.client.connection import CommandRejected
from plural.host.preview import BRIDGE_LOADER
from plural.protocol.commands import PreviewOpen, PreviewSet
from plural.protocol.events import PreviewChanged, PreviewOpened, SessionSnapshot
from plural.protocol.models import Role
from plural.relay.rooms import _cookie_in_room  # pyright: ignore[reportPrivateUsage]
from tests.e2e.support import Session


async def test_only_host_shares_and_late_viewers_discover_preview(session: Session) -> None:
    owner = await session.owner()
    guest = await session.guest("Alia")
    with pytest.raises(CommandRejected):
        await guest.client.send(PreviewSet(port=3000))
    await owner.client.send(PreviewSet(port=3000, title="Landing"))
    preview = (await guest.next(PreviewChanged)).preview
    assert preview is not None
    assert (preview.port, preview.title) == (3000, "Landing")
    late = await session.guest("Viewer", Role.VIEWER)
    snapshot = next(event for event in late.events if isinstance(event, SessionSnapshot))
    assert snapshot.state.preview == preview
    await owner.client.send(PreviewSet())
    assert (await guest.next(PreviewChanged)).preview is None
    with pytest.raises(CommandRejected):
        await guest.client.send(PreviewOpen(preview_id=preview.id))


@asynccontextmanager
async def app_server(seen: list[bytes]) -> AsyncGenerator[int]:
    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await reader.readuntil(b"\r\n\r\n")
        length = next(
            (
                int(line.split(b":")[1])
                for line in head.lower().split(b"\r\n")
                if line.startswith(b"content-length:")
            ),
            0,
        )
        seen.append(head + await reader.readexactly(length))
        body = b"<html><head></head><body><button>go</button></body></html>"
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
            + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
            + body
        )
        await writer.drain()
        writer.close()

    async with await asyncio.start_server(serve, "127.0.0.1", 0) as server:
        yield server.sockets[0].getsockname()[1]


def request(
    port: int, method: str, path: str, headers: dict[str, str] | None = None, body: bytes = b""
) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request(method, path, body=body or None, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


@pytest.mark.parametrize("session", ["relay"], indirect=True)
async def test_a_shared_server_runs_through_the_relay_for_each_participant(
    session: Session,
) -> None:
    assert session.relay is not None
    relay = session.relay.port
    owner = await session.owner()
    guest = await session.guest("Alia")
    seen: list[bytes] = []
    async with app_server(seen) as port:
        await owner.client.send(PreviewSet(port=port))
        preview = (await guest.next(PreviewChanged)).preview
        assert preview is not None
        await guest.client.send(PreviewOpen(preview_id=preview.id))
        link = "/" + (await guest.next(PreviewOpened)).path
        assert not any(isinstance(event, PreviewOpened) for event in owner.events)

        status, _, body = await asyncio.to_thread(
            request, relay, "POST", link + "form", {"Sec-Fetch-Dest": "iframe"}, b"a=1"
        )
        assert status == 200
        assert b"<button>go</button>" in body
        assert BRIDGE_LOADER.encode() in body
        assert seen[-1].startswith(b"POST /form HTTP/1.1")
        assert seen[-1].endswith(b"a=1")

        # A body near the relay's limit reaches the app without costing the host its connection.
        big = b"x" * 900_000
        status, _, _ = await asyncio.to_thread(request, relay, "POST", link + "upload", {}, big)
        assert status == 200
        assert seen[-1].endswith(big)
        status, _, _ = await asyncio.to_thread(
            request, relay, "GET", link.rsplit("/", 2)[0] + "/x/"
        )
        assert status == 404

        # A page of its own on the relay's address is refused; a page's root path comes back.
        status, _, _ = await asyncio.to_thread(
            request, relay, "GET", link, {"Sec-Fetch-Dest": "document"}
        )
        assert status == 403
        status, headers, _ = await asyncio.to_thread(
            request,
            relay,
            "GET",
            "/assets/app.js?v=1",
            {"Referer": f"http://127.0.0.1:{relay}{link}page", "Host": f"127.0.0.1:{relay}"},
        )
        assert status == 307
        assert urlsplit(headers["location"]).path == link + "assets/app.js"

        await owner.client.send(PreviewSet())
        await guest.next(PreviewChanged)
        status, _, _ = await asyncio.to_thread(request, relay, "GET", link)
        assert status == 404


def test_a_preview_cookie_stays_in_its_room() -> None:
    assert _cookie_in_room("sid=1; Path=/p/r_1/s/; Secure", "r_1")
    assert not _cookie_in_room("sid=1; Path=/", "r_1")
    assert not _cookie_in_room("sid=1; Path=/p/r_2/s/", "r_1")
    assert not _cookie_in_room("sid=1; Path=/p/r_1/s/; Domain=relay.example", "r_1")
