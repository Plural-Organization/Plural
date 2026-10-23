import asyncio
import secrets
from contextlib import suppress
from dataclasses import dataclass, field

from pydantic import ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect

from plural.protocol.relay import RELAY_MESSAGES, RelayClosed, RelayFrame, RelayOpen
from plural.relay.limits import RelayLimits, TokenBucket
from plural.security.tokens import TokenVerifier

CLOSE_BAD_OPEN = 4400
CLOSE_BAD_PROOF = 4401
CLOSE_NO_HOST = 4404
CLOSE_ROOM_TAKEN = 4409
CLOSE_TOO_LARGE = 4413
CLOSE_RATE_LIMITED = 4429
CLOSE_SLOW = 4408


class Outbox:
    def __init__(self, socket: WebSocket, size: int) -> None:
        self._socket = socket
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=size)

    def push(self, text: str) -> bool:
        try:
            self._queue.put_nowait(text)
        except asyncio.QueueFull:
            return False
        return True

    async def pump(self) -> None:
        with suppress(WebSocketDisconnect, RuntimeError):
            while True:
                await self._socket.send_text(await self._queue.get())

    async def close(self, code: int) -> None:
        with suppress(RuntimeError):
            await self._socket.close(code)


@dataclass(slots=True)
class Room:
    public_key: str
    host: Outbox | None = None
    guests: dict[str, Outbox] = field(default_factory=dict[str, Outbox])

    def current_host(self) -> Outbox | None:
        return self.host


class Rooms:
    def __init__(self, limits: RelayLimits) -> None:
        self._limits = limits
        self._rooms: dict[str, Room] = {}

    @property
    def room_count(self) -> int:
        return len(self._rooms)

    @property
    def guest_count(self) -> int:
        return sum(len(room.guests) for room in self._rooms.values())

    async def serve_host(self, socket: WebSocket, room_id: str) -> None:
        await socket.accept()
        try:
            opening = RelayOpen.model_validate_json(await socket.receive_text())
        except (ValidationError, WebSocketDisconnect):
            await socket.close(CLOSE_BAD_OPEN)
            return
        verifier = TokenVerifier.from_b64(opening.public_key)
        if opening.room != room_id or not verifier.verify_proof(room_id.encode(), opening.proof):
            await socket.close(CLOSE_BAD_PROOF)
            return
        room = self._rooms.get(room_id)
        if room is None:
            if len(self._rooms) >= self._limits.max_rooms:
                await socket.close(CLOSE_RATE_LIMITED)
                return
            room = self._rooms[room_id] = Room(public_key=opening.public_key)
        elif room.public_key != opening.public_key:
            await socket.close(CLOSE_ROOM_TAKEN)
            return
        if room.host is not None:
            await room.host.close(CLOSE_ROOM_TAKEN)
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
                    case RelayOpen():
                        pass
        except (WebSocketDisconnect, ValidationError):
            pass
        finally:
            pump.cancel()
            if room.host is outbox:
                room.host = None
                for connection_id in list(room.guests):
                    await self._drop(room, connection_id, CLOSE_NO_HOST)

    async def serve_guest(self, socket: WebSocket, room_id: str) -> None:
        await socket.accept()
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

    async def _drop(self, room: Room, connection_id: str, code: int) -> None:
        guest = room.guests.pop(connection_id, None)
        if guest is not None:
            await guest.close(code)
