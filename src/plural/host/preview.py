"""Bounded GET-only access to a host-selected loopback HTTP server."""

import asyncio
import http.client
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

MAX_RESOURCE_BYTES = 2_000_000
MAX_CONCURRENT = 4
TIMEOUT_S = 10


class PreviewError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Resource:
    status: int
    media_type: str
    body: bytes


def resource_path(path: str) -> str:
    if not path.startswith("/") or path.startswith("//"):
        raise PreviewError("preview needs a relative resource path")
    decoded = unquote(path)
    if any(ord(char) < 32 or ord(char) == 127 for char in decoded) or "\\" in decoded:
        raise PreviewError("invalid preview path")
    parts = urlsplit(path)
    if parts.scheme or parts.netloc or parts.fragment:
        raise PreviewError("invalid preview path")
    segments = unquote(parts.path).lower().split("/")
    # Dot-files hold secrets (.env, .git, .npmrc) and are matched without case: macOS ignores it.
    if any(part.startswith(".") and part != ".well-known" for part in segments):
        raise PreviewError("private paths are not available in previews")
    # Dev servers act on these GETs, opening files in the host's editor or serving the whole disk,
    # under a base path too.
    if any(part.startswith("__") or part == "@fs" for part in segments):
        raise PreviewError("dev server endpoints are not available in previews")
    try:
        path.encode("ascii")
    except UnicodeEncodeError:
        raise PreviewError("preview paths must be URL encoded") from None
    return path


def _fetch(port: int, path: str) -> Resource:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=TIMEOUT_S)
    try:
        connection.request("GET", path, headers={"Accept-Encoding": "identity"})
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise PreviewError("preview redirects are not supported; open the final path")
        if response.getheader("Content-Encoding", "identity").lower() != "identity":
            raise PreviewError("compressed preview responses are not supported")
        body = response.read(MAX_RESOURCE_BYTES + 1)
        if len(body) > MAX_RESOURCE_BYTES:
            raise PreviewError("preview resource exceeds 2 MB")
        return Resource(
            response.status, response.getheader("Content-Type", "application/octet-stream"), body
        )
    except (OSError, http.client.HTTPException):
        raise PreviewError("local preview server is unavailable") from None
    finally:
        connection.close()


class PreviewFetcher:
    def __init__(self) -> None:
        self._active = 0

    async def fetch(self, port: int, path: str) -> Resource:
        path = resource_path(path)
        if not 1 <= port <= 65535:
            raise PreviewError("invalid preview port")
        if self._active >= MAX_CONCURRENT:
            raise PreviewError("preview is busy; retry shortly")
        self._active += 1
        try:
            return await asyncio.to_thread(_fetch, port, path)
        finally:
            self._active -= 1
