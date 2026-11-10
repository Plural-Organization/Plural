import asyncio
import base64
import binascii
from collections.abc import Awaitable, Callable
from contextlib import suppress

import structlog
from pydantic import ValidationError
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from plural.host.inbox import Disconnected, Inbox, Incoming
from plural.host.preview import PreviewProxy
from plural.protocol.envelope import Envelope
from plural.protocol.relay import (
    RELAY_MESSAGES,
    USER_AGENT,
    RelayClosed,
    RelayFrame,
    RelayHttpReply,
    RelayHttpRequest,
    RelayOpen,
)
from plural.security.tokens import TokenSigner

log = structlog.get_logger(__name__)

# Raw bytes per reply part, kept well under the relay's message limit once in base64.
REPLY_CHUNK_BYTES = 512 * 1024
# What the relay may send: a guest's message, or a preview request's body in base64 with headers.
MAX_RELAY_MESSAGE_BYTES = 8 * 1024 * 1024


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
        preview: PreviewProxy | None = None,
        entitlement: Callable[[], Awaitable[str | None]] | None = None,
    ) -> None:
        self._url = url.rstrip("/")
        self._room = room
        self._signer = signer
        self._queue_size = queue_size
        self._max_delay_s = max_delay_s
        self._preview = preview
        self._entitlement = entitlement

    async def serve(self, inbox: Inbox) -> None:
        delay = 0.5
        while True:
            try:
                async with connect(
                    f"{self._url}/host/{self._room}",
                    user_agent_header=USER_AGENT,
                    max_size=MAX_RELAY_MESSAGE_BYTES,
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
            entitlement=None if self._entitlement is None else await self._entitlement(),
        )
        await socket.send(opening.model_dump_json())
        outbox: asyncio.Queue[str] = asyncio.Queue(maxsize=self._queue_size)
        links: dict[str, RelayConnection] = {}
        requests: set[asyncio.Task[None]] = set()
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
                            await inbox.put_external(
                                Incoming(link, Envelope.model_validate_json(data))
                            )
                        except ValidationError:
                            continue
                    case RelayClosed(conn=connection_id):
                        closed = links.pop(connection_id, None)
                        if closed is not None:
                            await inbox.put_external(Disconnected(closed))
                    case RelayHttpRequest() if self._preview is not None:
                        task = asyncio.create_task(_answer(self._preview, message, outbox))
                        requests.add(task)
                        task.add_done_callback(requests.discard)
                    case RelayOpen() | RelayHttpRequest() | RelayHttpReply():
                        pass
        finally:
            writer.cancel()
            for task in requests:
                task.cancel()
            for link in links.values():
                await inbox.put_external(Disconnected(link))


async def _answer(
    preview: PreviewProxy, request: RelayHttpRequest, outbox: asyncio.Queue[str]
) -> None:
    try:
        body = base64.b64decode(request.body, validate=True)
    except binascii.Error:
        await outbox.put(RelayHttpReply(id=request.id, status=400, end=True).model_dump_json())
        return
    try:
        reply = await preview.handle(request.method, request.path, request.headers, body)
    except Exception:
        # Whatever went wrong, the browser hears now rather than at the relay's timeout.
        log.exception("preview.request_failed")
        await outbox.put(RelayHttpReply(id=request.id, status=502, end=True).model_dump_json())
        return
    parts = [
        reply.body[at : at + REPLY_CHUNK_BYTES]
        for at in range(0, len(reply.body), REPLY_CHUNK_BYTES)
    ] or [b""]
    for index, part in enumerate(parts):
        first = index == 0
        await outbox.put(
            RelayHttpReply(
                id=request.id,
                status=reply.status if first else 0,
                headers=reply.headers if first else [],
                body=base64.b64encode(part).decode(),
                end=index == len(parts) - 1,
            ).model_dump_json()
        )


async def _pump(socket: ClientConnection, outbox: asyncio.Queue[str]) -> None:
    with suppress(ConnectionClosed):
        while True:
            await socket.send(await outbox.get())
