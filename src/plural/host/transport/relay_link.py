import asyncio
from contextlib import suppress

import structlog
from pydantic import ValidationError
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from plural.host.inbox import Disconnected, Inbox, Incoming
from plural.protocol.envelope import Envelope
from plural.protocol.relay import RELAY_MESSAGES, RelayClosed, RelayFrame, RelayOpen
from plural.security.tokens import TokenSigner

log = structlog.get_logger(__name__)


class RelayConnection:
    def __init__(self, connection_id: str, outbox: asyncio.Queue[str]) -> None:
        self._id = connection_id
        self._outbox = outbox

    @property
    def id(self) -> str:
        return self._id

    def send(self, envelope: Envelope) -> None:
        frame = RelayFrame(conn=self._id, data=envelope.model_dump_json())
        try:
            self._outbox.put_nowait(frame.model_dump_json())
        except asyncio.QueueFull:
            log.warning("relay.outbox_full", connection=self._id)

    def close(self, reason: str) -> None:
        with suppress(asyncio.QueueFull):
            self._outbox.put_nowait(RelayClosed(conn=self._id).model_dump_json())


class RelayLink:
    def __init__(
        self,
        *,
        url: str,
        room: str,
        signer: TokenSigner,
        queue_size: int = 4096,
        max_delay_s: float = 5,
    ) -> None:
        self._url = url.rstrip("/")
        self._room = room
        self._signer = signer
        self._queue_size = queue_size
        self._max_delay_s = max_delay_s

    async def serve(self, inbox: Inbox) -> None:
        delay = 0.5
        while True:
            try:
                async with connect(f"{self._url}/host/{self._room}") as socket:
                    delay = 0.5
                    await self._session(socket, inbox)
            except (OSError, WebSocketException) as error:
                log.warning("relay.disconnected", error=str(error))
            await asyncio.sleep(delay)
            delay = min(delay * 2, self._max_delay_s)

    async def _session(self, socket: ClientConnection, inbox: Inbox) -> None:
        opening = RelayOpen(
            room=self._room,
            public_key=self._signer.verifier.public_b64(),
            proof=self._signer.prove(self._room.encode()),
        )
        await socket.send(opening.model_dump_json())
        outbox: asyncio.Queue[str] = asyncio.Queue(maxsize=self._queue_size)
        links: dict[str, RelayConnection] = {}
        writer = asyncio.create_task(_pump(socket, outbox))
        try:
            async for raw in socket:
                try:
                    message = RELAY_MESSAGES.validate_json(raw)
                except ValidationError:
                    continue
                match message:
                    case RelayFrame(conn=connection_id, data=data):
                        link = links.get(connection_id)
                        if link is None:
                            link = links[connection_id] = RelayConnection(connection_id, outbox)
                        try:
                            inbox.put(Incoming(link, Envelope.model_validate_json(data)))
                        except ValidationError:
                            continue
                    case RelayClosed(conn=connection_id):
                        closed = links.pop(connection_id, None)
                        if closed is not None:
                            inbox.put(Disconnected(closed))
                    case RelayOpen():
                        pass
        finally:
            writer.cancel()
            for link in links.values():
                inbox.put(Disconnected(link))


async def _pump(socket: ClientConnection, outbox: asyncio.Queue[str]) -> None:
    with suppress(ConnectionClosed):
        while True:
            await socket.send(await outbox.get())
