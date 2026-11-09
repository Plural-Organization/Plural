import asyncio

import pytest

from plural.host.preview import (
    BRIDGE_LOADER,
    MAX_CONCURRENT,
    MAX_RESPONSE_BYTES,
    PreviewError,
    PreviewProxy,
    resource_path,
)


@pytest.mark.parametrize(
    "path",
    [
        "http://example.com",
        "//example.com/x",
        "/x%0d%0aHost:x",
        "/a\\b",
        "/.env",
        "/.env.local",
        "/%2e%2e/a",
        "/.git/config",
        "/.GIT/config",
        "/.npmrc",
        "/__open-in-editor?file=a",
        "/@fs/etc/passwd",
        "/app/@fs/etc/passwd",
        "/app/__open-in-editor?file=a",
        "/x#fragment",
    ],
)
def test_preview_rejects_authorities_controls_and_private_paths(path: str) -> None:
    with pytest.raises(PreviewError):
        resource_path(path)


def test_preview_keeps_encoded_paths_and_queries() -> None:
    assert resource_path("/assets/a%20b.svg?v=2") == "/assets/a%20b.svg?v=2"


async def _serve_once(
    status: int, headers: bytes, body: bytes, requests: list[bytes]
) -> asyncio.Server:
    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        requests.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(
            f"HTTP/1.1 {status} Test\r\nContent-Length: {len(body)}\r\n".encode()
            + headers
            + b"Connection: close\r\n\r\n"
            + body
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    return await asyncio.start_server(serve, "127.0.0.1", 0)


def _proxy(port: int, online: bool = True) -> tuple[PreviewProxy, str]:
    proxy = PreviewProxy("r_1", online=lambda _participant: online)
    proxy.share(port)
    return proxy, "/" + proxy.grant("p_1")


async def test_preview_passes_requests_as_from_the_app_and_keeps_answers_under_the_link() -> None:
    requests: list[bytes] = []
    page = b"<html><head><title>x</title></head><body>hi</body></html>"
    headers = b"Content-Type: text/html\r\nLocation: /next\r\n"
    async with await _serve_once(302, headers, page, requests) as server:
        proxy, link = _proxy(server.sockets[0].getsockname()[1])
        reply = await proxy.handle(
            "POST",
            link + "form?a=1",
            [
                ("Origin", "https://relay.example"),
                ("Referer", f"https://relay.example{link}home"),
                ("Cookie", "sid=1"),
                ("X-Forwarded-For", "1.2.3.4"),
            ],
            b"name=x",
        )
    assert reply.status == 302
    assert dict(reply.headers)["location"] == link + "next"
    assert reply.body.index(BRIDGE_LOADER.encode()) > reply.body.index(b"<head>")
    sent = requests[0].decode().lower()
    assert sent.startswith("post /form?a=1 http/1.1\r\n")
    assert "host: localhost:" in sent
    assert "origin: http://localhost:" in sent
    assert "referer: http://localhost:" in sent
    assert sent.count("/home") == 1
    assert "relay.example" not in sent
    assert "x-forwarded-for" not in sent
    assert "cookie: sid=1" in sent


async def test_preview_scopes_cookies_and_drops_framing_headers() -> None:
    headers = b"Set-Cookie: sid=1; Path=/; Domain=localhost; HttpOnly\r\nX-Frame-Options: DENY\r\n"
    async with await _serve_once(200, headers, b"ok", []) as server:
        proxy, link = _proxy(server.sockets[0].getsockname()[1])
        reply = await proxy.handle("GET", link, [], b"")
    kept = dict(reply.headers)
    assert "x-frame-options" not in kept
    cookie = kept["set-cookie"]
    assert cookie.startswith("sid=1")
    assert f"Path={link.rstrip('/')}/" in cookie
    assert "Domain" not in cookie
    assert "HttpOnly" in cookie


@pytest.mark.parametrize(
    ("target", "status"),
    [
        ("/p/r_2/{secret}/", 404),
        ("/p/r_1/wrong/", 404),
        ("/p/r_1/{secret}/.env", 403),
        ("/p/r_1/{secret}/__nextjs_launch-editor", 403),
    ],
)
async def test_preview_refuses_other_links_and_private_paths(target: str, status: int) -> None:
    proxy, link = _proxy(1)
    secret = link.split("/")[3]
    reply = await proxy.handle("GET", target.format(secret=secret), [], b"")
    assert reply.status == status


async def test_a_link_ends_with_its_holder_and_with_the_share() -> None:
    offline, link = _proxy(1, online=False)
    assert (await offline.handle("GET", link, [], b"")).status == 404
    proxy, link = _proxy(1)
    assert proxy.grant("p_1") == link[1:]
    proxy.share(2)
    assert (await proxy.handle("GET", link, [], b"")).status == 404
    assert proxy.grant("p_1") != link[1:]


@pytest.mark.parametrize(
    ("headers", "body"),
    [
        (b"Content-Encoding: gzip\r\n", b"compressed"),
        (b"", b"x" * (MAX_RESPONSE_BYTES + 1)),
    ],
)
async def test_preview_answers_are_bounded(headers: bytes, body: bytes) -> None:
    async with await _serve_once(200, headers, body, []) as server:
        proxy, link = _proxy(server.sockets[0].getsockname()[1])
        reply = await proxy.handle("GET", link, [], b"")
    assert reply.status == 502


@pytest.mark.parametrize(
    ("page", "after"),
    [
        (b"<!DOCTYPE html><html lang=en><body>x", b"<html lang=en>"),
        (b"<!doctype html><p>x", b"<!doctype html>"),
        (b"<p>x", b""),
    ],
)
async def test_the_bridge_loader_keeps_the_doctype_first(page: bytes, after: bytes) -> None:
    async with await _serve_once(200, b"Content-Type: text/html\r\n", page, []) as server:
        proxy, link = _proxy(server.sockets[0].getsockname()[1])
        reply = await proxy.handle("GET", link, [], b"")
    at = page.index(after) + len(after)
    assert reply.body == page[:at] + BRIDGE_LOADER.encode() + page[at:]


async def test_a_burst_of_requests_waits_instead_of_failing() -> None:
    served = 0

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal served
        await reader.readuntil(b"\r\n\r\n")
        await asyncio.sleep(0.05)
        served += 1
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await writer.drain()
        writer.close()

    async with await asyncio.start_server(serve, "127.0.0.1", 0) as server:
        proxy, link = _proxy(server.sockets[0].getsockname()[1])
        replies = await asyncio.gather(
            *(
                proxy.handle("GET", f"{link}m{index}.js", [], b"")
                for index in range(MAX_CONCURRENT * 3)
            )
        )
    assert [reply.status for reply in replies] == [200] * (MAX_CONCURRENT * 3)
    assert served == MAX_CONCURRENT * 3
