import asyncio
import base64
import binascii
import re
import secrets
import time
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from dataclasses import dataclass, field

import structlog
from pydantic import ValidationError
from starlette.requests import ClientDisconnect, Request
from starlette.responses import PlainTextResponse, Response, StreamingResponse
from starlette.websockets import WebSocket, WebSocketDisconnect

from plural.protocol.relay import (
    RELAY_MESSAGES,
    RelayClosed,
    RelayFrame,
    RelayHttpReply,
    RelayHttpRequest,
    RelayOpen,
)
from plural.relay.entitlements import EntitlementWatch, Outcome
from plural.relay.limits import PeerGate, RelayLimits, TokenBucket, peer_of
from plural.security.tokens import TokenVerifier

CLOSE_BAD_OPEN = 4400
CLOSE_BAD_PROOF = 4401
CLOSE_NO_HOST = 4404
CLOSE_ROOM_TAKEN = 4409
CLOSE_TOO_LARGE = 4413
CLOSE_RATE_LIMITED = 4429
CLOSE_SLOW = 4408

log = structlog.get_logger(__name__)

# What a preview's answer may not set on the relay's address, which every preview shares.
_UNSAFE_PREVIEW_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "transfer-encoding",
        "trailer",
        "upgrade",
        "content-length",
        "content-encoding",
        "strict-transport-security",
        "clear-site-data",
        "service-worker-allowed",
        "alt-svc",
    }
)
# What a host hands out after `/p/<room>/` (`token_urlsafe(24)`); anything else is not worth
# troubling the host with.
_PREVIEW_SECRET = re.compile(r"[A-Za-z0-9_-]{32}(/|$)")
_FORWARDED_HEADERS = frozenset({"host", "connection", "upgrade", "content-length", "forwarded"})


class Outbox:
    def __init__(self, socket: WebSocket, size: int) -> None:
        self._socket = socket
        self._queue: asyncio.Queue[str | int] = asyncio.Queue(maxsize=size)

    def push(self, text: str) -> bool:
        try:
            self._queue.put_nowait(text)
        except asyncio.QueueFull:
            return False
        return True

    async def pump(self) -> None:
        with suppress(WebSocketDisconnect, RuntimeError):
            while True:
                item = await self._queue.get()
                if isinstance(item, int):
                    await self._socket.close(item)
                    return
                await self._socket.send_text(item)

    async def close(self, code: int) -> None:
        try:
            self._queue.put_nowait(code)
        except asyncio.QueueFull:
            with suppress(RuntimeError):
                await self._socket.close(code)


@dataclass(slots=True)
class Room:
    public_key: str
    host: Outbox | None = None
    guests: dict[str, Outbox] = field(default_factory=dict[str, Outbox])
    vacated_at: float | None = None
    requests: dict[str, "asyncio.Queue[RelayHttpReply | None]"] = field(
        default_factory=dict[str, "asyncio.Queue[RelayHttpReply | None]"]
    )
    preview_bucket: TokenBucket | None = None

    def current_host(self) -> Outbox | None:
        return self.host


class Rooms:
    def __init__(
        self,
        limits: RelayLimits,
        *,
        clock: Callable[[], float] = time.monotonic,
        proxy_hops: int = 0,
        entitlements: EntitlementWatch | None = None,
    ) -> None:
        self._entitlements = entitlements
        self._limits = limits
        self._clock = clock
        self._proxy_hops = proxy_hops
        self._gate = PeerGate(limits, clock)
        self._rooms: dict[str, Room] = {}
        self._preview_peers: dict[str, TokenBucket] = {}

    @property
    def room_count(self) -> int:
        self._sweep()
        return len(self._rooms)

    @property
    def guest_count(self) -> int:
        return sum(len(room.guests) for room in self._rooms.values())

    def _sweep(self) -> None:
        now = self._clock()
        for room_id, room in list(self._rooms.items()):
            if (
                room.host is None
                and not room.guests
                and room.vacated_at is not None
                and now - room.vacated_at >= self._limits.room_ttl_s
            ):
                del self._rooms[room_id]

    def _peer(self, socket: WebSocket) -> str:
        return peer_of(
            socket.headers.get("x-forwarded-for"),
            socket.client.host if socket.client else None,
            self._proxy_hops,
        )

    async def serve_host(self, socket: WebSocket, room_id: str) -> None:
        await socket.accept()
        peer = self._peer(socket)
        if not self._gate.admit(peer, host=True):
            await socket.close(CLOSE_RATE_LIMITED)
            return
        try:
            await self._serve_host(socket, room_id, peer)
        finally:
            self._gate.release(peer, host=True)

    async def serve_guest(self, socket: WebSocket, room_id: str) -> None:
        await socket.accept()
        peer = self._peer(socket)
        if not self._gate.admit(peer, host=False):
            await socket.close(CLOSE_RATE_LIMITED)
            return
        try:
            await self._serve_guest(socket, room_id)
        finally:
            self._gate.release(peer, host=False)

    async def _serve_host(self, socket: WebSocket, room_id: str, peer: str) -> None:
        try:
            opening = RelayOpen.model_validate_json(await socket.receive_text())
        except (ValidationError, WebSocketDisconnect):
            await socket.close(CLOSE_BAD_OPEN)
            return
        verifier = TokenVerifier.from_b64(opening.public_key)
        if opening.room != room_id or not verifier.verify_proof(room_id.encode(), opening.proof):
            await socket.close(CLOSE_BAD_PROOF)
            return
        self._note_entitlement(opening, room_id, peer)
        self._sweep()
        room = self._rooms.get(room_id)
        if room is None:
            if len(self._rooms) >= self._limits.max_rooms:
                await socket.close(CLOSE_RATE_LIMITED)
                return
            room = self._rooms[room_id] = Room(public_key=opening.public_key)
            log.info("relay.room_opened", room=room_id, peer=peer)
        elif room.public_key != opening.public_key:
            await socket.close(CLOSE_ROOM_TAKEN)
            return
        if room.host is not None:
            await room.host.close(CLOSE_ROOM_TAKEN)
            for waiting in room.requests.values():
                _abandon(waiting)
            room.requests.clear()
        outbox = room.host = Outbox(socket, self._limits.host_queue)
        pump = asyncio.create_task(outbox.pump())
        try:
            while True:
                message = RELAY_MESSAGES.validate_json(await socket.receive_text())
                match message:
                    case RelayFrame(conn=connection_id, data=data):
                        guest = room.guests.get(connection_id)
                        if guest is not None and not guest.push(data):
                            await self._drop(room, connection_id, CLOSE_SLOW)
                    case RelayClosed(conn=connection_id):
                        await self._drop(room, connection_id, 1000)
                    case RelayHttpReply(id=request_id):
                        waiting = room.requests.get(request_id)
                        if waiting is not None:
                            try:
                                waiting.put_nowait(message)
                            except asyncio.QueueFull:
                                room.requests.pop(request_id, None)
                                _abandon(waiting)
                            if message.end:
                                room.requests.pop(request_id, None)
                    case RelayOpen() | RelayHttpRequest():
                        pass
        except (WebSocketDisconnect, ValidationError):
            pass
        finally:
            pump.cancel()
            if room.host is outbox:
                room.host = None
                room.vacated_at = self._clock()
                for waiting in room.requests.values():
                    _abandon(waiting)
                room.requests.clear()
                for connection_id in list(room.guests):
                    await self._drop(room, connection_id, CLOSE_NO_HOST)

    def _note_entitlement(self, opening: RelayOpen, room_id: str, peer: str) -> None:
        """Records what the host's certificate says. It never refuses and never raises."""
        if self._entitlements is None:
            return
        try:
            outcome, claims = self._entitlements.check(opening)
            log.info(
                "relay.entitlement",
                room=room_id,
                peer=peer,
                outcome=outcome.value,
                account=claims.account if outcome is Outcome.VALID and claims else None,
            )
        except Exception:
            log.exception("relay.entitlement_check_failed", room=room_id)

    async def _serve_guest(self, socket: WebSocket, room_id: str) -> None:
        self._sweep()
        room = self._rooms.get(room_id)
        if room is None or room.host is None:
            await socket.close(CLOSE_NO_HOST)
            return
        if len(room.guests) >= self._limits.max_guests_per_room:
            await socket.close(CLOSE_RATE_LIMITED)
            return
        connection_id = f"g_{secrets.token_hex(8)}"
        outbox = room.guests[connection_id] = Outbox(socket, self._limits.guest_queue)
        bucket = TokenBucket(self._limits.messages_per_second, self._limits.burst)
        pump = asyncio.create_task(outbox.pump())
        try:
            while True:
                text = await socket.receive_text()
                if len(text.encode()) > self._limits.max_message_bytes:
                    await socket.close(CLOSE_TOO_LARGE)
                    return
                if not bucket.take():
                    await socket.close(CLOSE_RATE_LIMITED)
                    return
                host = room.current_host()
                if host is None or not host.push(
                    RelayFrame(conn=connection_id, data=text).model_dump_json()
                ):
                    await socket.close(CLOSE_NO_HOST)
                    return
        except WebSocketDisconnect:
            pass
        finally:
            pump.cancel()
            if room.guests.pop(connection_id, None) is not None and (host := room.current_host()):
                host.push(RelayClosed(conn=connection_id).model_dump_json())

    async def serve_preview(self, request: Request, room_id: str, under: str) -> Response:
        """Hands a browser's request for a host's preview to that host and streams its answer."""
        limits = self._limits
        room = self._rooms.get(room_id)
        if room is None or room.host is None or not _PREVIEW_SECRET.match(under):
            return PlainTextResponse("this preview is not shared right now", 404)
        # Previews open inside Plural; a page of its own here would pass for the relay's.
        if request.headers.get("sec-fetch-dest") == "document":
            return PlainTextResponse("previews open inside Plural", 403)
        if room.preview_bucket is None:
            room.preview_bucket = TokenBucket(
                limits.preview_requests_per_second, limits.preview_burst, self._clock
            )
        if not room.preview_bucket.take() or not self._preview_peer(request).take():
            return PlainTextResponse("too many preview requests", 429)
        if len(room.requests) >= limits.max_preview_requests:
            return PlainTextResponse("the preview is busy, retry shortly", 503)
        body = bytearray()
        try:
            async for chunk in request.stream():
                body += chunk
                if len(body) > limits.max_preview_body_bytes:
                    return PlainTextResponse("the request is too large for a preview", 413)
        except ClientDisconnect:
            return PlainTextResponse("", 499)
        request_id = secrets.token_hex(8)
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        forwarded = RelayHttpRequest(
            id=request_id,
            method=request.method,
            path=target,
            headers=[
                (name, value)
                for name, value in request.headers.items()
                if name not in _FORWARDED_HEADERS
            ],
            body=base64.b64encode(body).decode(),
        )
        waiting: asyncio.Queue[RelayHttpReply | None] = asyncio.Queue(maxsize=64)
        room.requests[request_id] = waiting
        if not room.host.push(forwarded.model_dump_json()):
            room.requests.pop(request_id, None)
            return PlainTextResponse("the host is busy, retry shortly", 503)
        first = await self._next_part(room, request_id, waiting)
        if first is None:
            room.requests.pop(request_id, None)
            return PlainTextResponse("the host did not answer", 504)
        try:
            data = base64.b64decode(first.body, validate=True)
        except binascii.Error:
            room.requests.pop(request_id, None)
            return PlainTextResponse("the host sent a broken answer", 502)
        headers = _safe_preview_headers(first.headers, room_id)

        async def rest() -> AsyncIterator[bytes]:
            try:
                yield data
                if first.end:
                    return
                while (part := await self._next_part(room, request_id, waiting)) is not None:
                    yield base64.b64decode(part.body)
                    if part.end:
                        return
            finally:
                room.requests.pop(request_id, None)

        response = StreamingResponse(rest(), status_code=first.status or 502)
        response.raw_headers = [*response.raw_headers, *headers]
        return response

    def _preview_peer(self, request: Request) -> TokenBucket:
        peer = peer_of(
            request.headers.get("x-forwarded-for"),
            request.client.host if request.client else None,
            self._proxy_hops,
        )
        bucket = self._preview_peers.get(peer)
        if bucket is None:
            if len(self._preview_peers) >= 10_000:
                for idle in [key for key, kept in self._preview_peers.items() if kept.full()]:
                    del self._preview_peers[idle]
            bucket = self._preview_peers[peer] = TokenBucket(
                self._limits.preview_requests_per_second, self._limits.preview_burst, self._clock
            )
        return bucket

    async def _next_part(
        self, room: Room, request_id: str, waiting: "asyncio.Queue[RelayHttpReply | None]"
    ) -> RelayHttpReply | None:
        try:
            return await asyncio.wait_for(waiting.get(), self._limits.preview_timeout_s)
        except TimeoutError:
            room.requests.pop(request_id, None)
            return None

    async def _drop(self, room: Room, connection_id: str, code: int) -> None:
        guest = room.guests.pop(connection_id, None)
        if guest is not None:
            await guest.close(code)


def _abandon(waiting: "asyncio.Queue[RelayHttpReply | None]") -> None:
    """Ends a request whose answer will not come in full."""
    while not waiting.empty():
        waiting.get_nowait()
    waiting.put_nowait(None)


def _safe_preview_headers(
    headers: list[tuple[str, str]], room_id: str
) -> list[tuple[bytes, bytes]]:
    kept: list[tuple[bytes, bytes]] = []
    for name, value in headers:
        lowered = name.lower()
        if lowered in _UNSAFE_PREVIEW_HEADERS or "\n" in value or "\r" in value:
            continue
        # A cookie stays on its own room's previews.
        if lowered == "set-cookie" and not _cookie_in_room(value, room_id):
            continue
        kept.append((lowered.encode("latin-1"), value.encode("latin-1", "replace")))
    return kept


def _cookie_in_room(value: str, room_id: str) -> bool:
    attributes = [part.strip().lower() for part in value.split(";")[1:]]
    if any(part.startswith("domain") for part in attributes):
        return False
    paths = [part.split("=", 1)[1].strip() for part in attributes if part.startswith("path=")]
    return len(paths) == 1 and paths[0].startswith(f"/p/{room_id.lower()}/")
