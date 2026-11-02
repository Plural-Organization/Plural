import asyncio

import pytest

from plural.host.preview import MAX_RESOURCE_BYTES, PreviewError, PreviewFetcher, resource_path


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


@pytest.mark.parametrize(
    ("status", "headers", "body", "rejected"),
    [
        (200, b"Content-Type: image/png\r\n", b"\x89PNG", False),
        (302, b"Location: http://example.com/\r\n", b"", True),
        (200, b"Content-Encoding: gzip\r\n", b"compressed", True),
        (200, b"", b"x" * (MAX_RESOURCE_BYTES + 1), True),
    ],
)
async def test_preview_fetch_is_bounded_and_does_not_follow_redirects(
    status: int, headers: bytes, body: bytes, rejected: bool
) -> None:
    requests: list[bytes] = []

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

    async with await asyncio.start_server(serve, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        if rejected:
            with pytest.raises(PreviewError):
                await PreviewFetcher().fetch(port, "/image?v=1")
        else:
            resource = await PreviewFetcher().fetch(port, "/image?v=1")
            assert resource.status == 200
            assert resource.body == body
            assert resource.media_type == "image/png"
    assert len(requests) == 1
    assert requests[0].startswith(b"GET /image?v=1 HTTP/1.1\r\n")
    assert b"Accept-Encoding: identity" in requests[0]
