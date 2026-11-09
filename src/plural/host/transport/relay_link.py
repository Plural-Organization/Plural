import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress

import structlog
from pydantic import ValidationError
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from plural.host.inbox import Disconnected, Inbox, Incoming
from plural.protocol.envelope import Envelope
from plural.protocol.relay import (
    CALL_PREFIX,
    RELAY_MESSAGES,
    USER_AGENT,
    CallReply,
    RelayClosed,
    RelayFrame,
    RelayOpen,
)
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
        on_call: Callable[[str], Awaitable[str]] | None = None,
    ) -> None:
        self._on_call = on_call
        self._url = url.rstrip("/")
        self._room = room
        self._signer = signer
        self._queue_size = queue_size
        self._max_delay_s = max_delay_s

    async def serve(self, inbox: Inbox) -> None:
        delay = 0.5
        while True:
            try:
                async with connect(
                    f"{self._url}/host/{self._room}", user_agent_header=USER_AGENT
                ) as socket:
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
        calls: set[asyncio.Task[None]] = set()
        writer = asyncio.create_task(_pump(socket, outbox))
        try:
            async for raw in socket:
                try:
                    message = RELAY_MESSAGES.validate_json(raw)
                except ValidationError:
                    continue
                match message:
                    case RelayFrame(conn=connection_id, data=data) if connection_id.startswith(
                        CALL_PREFIX
                    ):
                        task = asyncio.create_task(self._answer(connection_id, data, outbox))
                        calls.add(task)
                        task.add_done_callback(calls.discard)
                    case RelayFrame(conn=connection_id, data=data):
                        link = links.get(connection_id)
                        if link is None:
                            link = links[connection_id] = RelayConnection(connection_id, outbox)
                        try:
                            await inbox.put_external(
                                Incoming(link, Envelope.model_validate_json(data))
                            )
                        except ValidationError:
                            continue
                    case RelayClosed(conn=connection_id):
                        closed = links.pop(connection_id, None)
                        if closed is not None:
                            await inbox.put_external(Disconnected(closed))
                    case RelayOpen():
                        pass
        finally:
            writer.cancel()
            for task in calls:
                task.cancel()
            for link in links.values():
                await inbox.put_external(Disconnected(link))

    async def _answer(self, connection_id: str, data: str, outbox: asyncio.Queue[str]) -> None:
        """A plain request through the relay: the import link, never a participant."""
        reply = CallReply(status=404).model_dump_json()
        if self._on_call is not None:
            try:
                reply = await self._on_call(data)
            except Exception:
                log.exception("relay.call_failed")
                reply = CallReply(status=500).model_dump_json()
        with suppress(asyncio.QueueFull):
            outbox.put_nowait(RelayFrame(conn=connection_id, data=reply).model_dump_json())


async def _pump(socket: ClientConnection, outbox: asyncio.Queue[str]) -> None:
    with suppress(ConnectionClosed):
        while True:
            await socket.send(await outbox.get())
