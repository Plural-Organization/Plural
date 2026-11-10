"""Opens the one loopback HTTP server the host shares to the session's browsers, through the relay.

Each participant asks for their own link, `p/<room>/<secret>/`; the relay hands what a browser asks
under it to this host, which passes it to the shared port and rewrites the answer to stay under it.
"""

import asyncio
import http.client
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

MAX_REQUEST_BYTES = 1_000_000
MAX_RESPONSE_BYTES = 16_000_000
MAX_CONCURRENT = 16
TIMEOUT_S = 30

# Hop-by-hop and what the relay or the browser decides; the rest of a request passes as sent.
_DROPPED_REQUEST = frozenset(
    {
        "host",
        "connection",
        "keep-alive",
        "upgrade",
        "te",
        "trailer",
        "transfer-encoding",
        "proxy-authorization",
        "accept-encoding",
        "content-length",
        "forwarded",
    }
)
# Kept from the app's answer only where they cannot reach past its own pages: a framed page would
# be refused, and the relay's origin is shared by every preview.
_DROPPED_RESPONSE = frozenset(
    {
        "connection",
        "keep-alive",
        "transfer-encoding",
        "trailer",
        "upgrade",
        "content-length",
        "content-encoding",
        "x-frame-options",
        "content-security-policy",
        "content-security-policy-report-only",
        "strict-transport-security",
        "clear-site-data",
        "service-worker-allowed",
        "alt-svc",
    }
)

# Runs the bridge the canvas sends in, so pointers and picking work over the app's own scripts.
BRIDGE_LOADER = (
    "<script>addEventListener('message',function l(e){var d=e.data;"
    "if(e.source!==parent||!d||d.from!=='plural-preview-bridge')return;"
    "removeEventListener('message',l);(0,eval)(d.code)})</script>"
)
_COOKIE_SCOPE = frozenset({"domain", "path", "samesite", "secure"})
# After `<head>`, or else after `<html>` or the doctype, so the page keeps its standards mode.
_ANCHORS = (
    re.compile(rb"<head\b[^>]*>", re.IGNORECASE),
    re.compile(rb"<html\b[^>]*>", re.IGNORECASE),
    re.compile(rb"<!doctype\b[^>]*>", re.IGNORECASE),
)


class PreviewError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Reply:
    status: int
    headers: list[tuple[str, str]]
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


def _refusal(status: int, text: str) -> Reply:
    return Reply(status, [("content-type", "text/plain; charset=utf-8")], text.encode())


class PreviewProxy:
    def __init__(self, room: str, *, online: Callable[[str], bool]) -> None:
        self._room = room
        self._online = online
        self._port: int | None = None
        self._grants: dict[str, str] = {}
        # A dev page asks for its modules all at once; past this many they wait their turn.
        self._slots = asyncio.Semaphore(MAX_CONCURRENT)

    def share(self, port: int | None) -> None:
        """A new port, or none, ends every link handed out for the old one."""
        self._port = port
        self._grants.clear()

    def grant(self, participant_id: str) -> str:
        for secret, holder in self._grants.items():
            if holder == participant_id:
                return self._path(secret)
        # 32 characters, the shape the relay checks before it passes a request on.
        secret = secrets.token_urlsafe(24)
        self._grants[secret] = participant_id
        return self._path(secret)

    def _path(self, secret: str) -> str:
        return f"p/{self._room}/{secret}/"

    async def handle(
        self, method: str, target: str, headers: list[tuple[str, str]], body: bytes
    ) -> Reply:
        """Answers `target`, the path under the relay: `/p/<room>/<secret>/<rest>`."""
        parts = target.split("/", 4)
        if len(parts) < 4 or parts[1] != "p" or parts[2] != self._room:
            return _refusal(404, "no such preview")
        port = self._port
        holder = self._grants.get(parts[3])
        # A link works while its holder is in the session: one who left or was removed loses it.
        if port is None or holder is None or not self._online(holder):
            return _refusal(404, "this preview is no longer shared")
        prefix = f"/p/{self._room}/{parts[3]}"
        try:
            path = resource_path("/" + (parts[4] if len(parts) == 5 else ""))
        except PreviewError as error:
            return _refusal(403, str(error))
        if len(body) > MAX_REQUEST_BYTES:
            return _refusal(413, "the request is too large for a preview")
        async with self._slots:
            try:
                return await asyncio.to_thread(_forward, port, prefix, method, path, headers, body)
            except PreviewError as error:
                return _refusal(502, str(error))


def _forward(
    port: int, prefix: str, method: str, path: str, headers: list[tuple[str, str]], body: bytes
) -> Reply:
    local = f"localhost:{port}"
    sent: dict[str, str] = {}
    for name, value in headers:
        lowered = name.lower()
        if lowered in _DROPPED_REQUEST or lowered.startswith(("x-forwarded-", "cf-", "x-real-")):
            continue
        # The app sees itself asked from its own address, which dev servers check before acting.
        if lowered == "origin":
            value = f"http://{local}"
        elif lowered == "referer":
            referer = urlsplit(value)
            if not referer.path.startswith(prefix):
                continue
            query = f"?{referer.query}" if referer.query else ""
            value = f"http://{local}{referer.path[len(prefix) :] or '/'}{query}"
        sent[lowered] = value
    sent["host"] = local
    sent["accept-encoding"] = "identity"
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=TIMEOUT_S)
    try:
        connection.request(method, path, body=body or None, headers=sent)
        response = connection.getresponse()
        if response.getheader("Content-Encoding", "identity").lower() != "identity":
            raise PreviewError("compressed preview responses are not supported")
        data = response.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            raise PreviewError("the preview resource exceeds 16 MB")
        kept: list[tuple[str, str]] = []
        for name, value in response.getheaders():
            lowered = name.lower()
            if lowered in _DROPPED_RESPONSE:
                continue
            if lowered == "location":
                value = _relayed_location(value, prefix, port)
            elif lowered == "set-cookie":
                value = _relayed_cookie(value, prefix)
            kept.append((lowered, value))
        media = (response.getheader("Content-Type") or "").lower()
        if method != "HEAD" and media.startswith("text/html"):
            data = _with_bridge(data)
        return Reply(response.status, kept, data)
    except (OSError, http.client.HTTPException):
        raise PreviewError("the local preview server is unavailable") from None
    finally:
        connection.close()


def _relayed_location(value: str, prefix: str, port: int) -> str:
    parts = urlsplit(value)
    if parts.netloc in (f"localhost:{port}", f"127.0.0.1:{port}", f"[::1]:{port}"):
        value = value[value.index(parts.netloc) + len(parts.netloc) :] or "/"
    elif parts.scheme or parts.netloc:
        return value
    return prefix + value if value.startswith("/") else value


def _relayed_cookie(value: str, prefix: str) -> str:
    """Keeps a cookie to this preview's own path: other previews share the relay's address."""
    pair, *attributes = value.split(";")
    kept = [
        part.strip()
        for part in attributes
        if part.strip().split("=", 1)[0].strip().lower() not in _COOKIE_SCOPE
    ]
    return "; ".join([pair.strip(), *kept]) + f"; Path={prefix}/; SameSite=None; Secure"


def _with_bridge(html: bytes) -> bytes:
    found = (anchor.search(html) for anchor in _ANCHORS)
    at = next((match.end() for match in found if match), 0)
    return html[:at] + BRIDGE_LOADER.encode() + html[at:]
