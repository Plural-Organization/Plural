import asyncio
import secrets
from contextlib import suppress
from dataclasses import dataclass

import structlog
from pydantic import ValidationError
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from plural.host.inbox import Disconnected, Inbox, Incoming
from plural.protocol.envelope import Envelope

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class _Close:
    reason: str


class WebSocketLink:
    def __init__(self, socket: ServerConnection, *, queue_size: int) -> None:
        self._id = f"c_{secrets.token_hex(8)}"
        self._socket = socket
        self._outbox: asyncio.Queue[Envelope | _Close] = asyncio.Queue(maxsize=queue_size)
        self._closing: asyncio.Task[None] | None = None

    @property
    def id(self) -> str:
        return self._id

    def send(self, envelope: Envelope) -> None:
        try:
            self._outbox.put_nowait(envelope)
        except asyncio.QueueFull:
            self._close_now("slow consumer")

    def close(self, reason: str) -> None:
        try:
            self._outbox.put_nowait(_Close(reason))
        except asyncio.QueueFull:
            self._close_now(reason)

    def _close_now(self, reason: str) -> None:
        if self._closing is None:
            self._closing = asyncio.create_task(self._socket.close(code=1008, reason=reason))

    async def pump(self) -> None:
        with suppress(ConnectionClosed):
            while True:
                item = await self._outbox.get()
                if isinstance(item, _Close):
                    await self._socket.close(code=1008, reason=item.reason)
                    return
                await self._socket.send(item.model_dump_json())


class DirectTransport:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        max_message_bytes: int = 4 * 1024 * 1024,
        queue_size: int = 1024,
    ) -> None:
        self._host = host
        self._port = port
        self._max_message_bytes = max_message_bytes
        self._queue_size = queue_size

    async def serve(self, inbox: Inbox) -> None:
        async def handler(socket: ServerConnection) -> None:
            await self._handle(inbox, socket)

        async with serve(
            handler, self._host, self._port, max_size=self._max_message_bytes
        ) as server:
            await server.serve_forever()

    async def _handle(self, inbox: Inbox, socket: ServerConnection) -> None:
        link = WebSocketLink(socket, queue_size=self._queue_size)
        pump = asyncio.create_task(link.pump())
        try:
            async for raw in socket:
                try:
                    envelope = Envelope.model_validate_json(raw)
                except ValidationError:
                    log.warning("direct.malformed_envelope", connection=link.id)
                    continue
                inbox.put(Incoming(link, envelope))
        except ConnectionClosed:
            pass
        finally:
            inbox.put(Disconnected(link))
            pump.cancel()
