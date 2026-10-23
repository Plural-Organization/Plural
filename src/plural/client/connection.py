import asyncio
import secrets
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import TracebackType
from typing import Self

from pydantic import ValidationError
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

from plural.protocol.codec import encode_command
from plural.protocol.commands import Command
from plural.protocol.envelope import Envelope, ErrorCode, ErrorInfo, Kind

MAX_MESSAGE_BYTES = 4 * 1024 * 1024


class CommandRejected(Exception):
    def __init__(self, error: ErrorInfo) -> None:
        super().__init__(f"{error.code}: {error.message}")
        self.error = error


class Wire:
    def __init__(self, socket: ClientConnection, *, room: str) -> None:
        self._socket = socket
        self._room = room
        self._pending: dict[str, asyncio.Future[Envelope]] = {}
        self._incoming: asyncio.Queue[Envelope | None] = asyncio.Queue()
        self._reader = asyncio.create_task(self._read())

    @classmethod
    async def open(cls, url: str, *, room: str) -> Self:
        return cls(await connect(url, max_size=MAX_MESSAGE_BYTES), room=room)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        await self.close()

    async def request(self, command: Command, *, token: str | None, timeout: float = 15) -> None:
        envelope = encode_command(
            command,
            envelope_id=f"c_{secrets.token_hex(10)}",
            room=self._room,
            ts=datetime.now(UTC),
            token=token,
        )
        future: asyncio.Future[Envelope] = asyncio.get_running_loop().create_future()
        self._pending[envelope.id] = future
        try:
            await self._socket.send(envelope.model_dump_json())
            ack = await asyncio.wait_for(future, timeout)
        finally:
            self._pending.pop(envelope.id, None)
        if not ack.ok:
            raise CommandRejected(
                ack.error or ErrorInfo(code=ErrorCode.INTERNAL, message="rejected")
            )

    async def envelopes(self) -> AsyncIterator[Envelope]:
        while (envelope := await self._incoming.get()) is not None:
            yield envelope

    async def close(self) -> None:
        self._reader.cancel()
        await self._socket.close()

    async def _read(self) -> None:
        try:
            async for raw in self._socket:
                try:
                    envelope = Envelope.model_validate_json(raw)
                except ValidationError:
                    continue
                if envelope.kind is Kind.ACK and envelope.re is not None:
                    future = self._pending.get(envelope.re)
                    if future is not None and not future.done():
                        future.set_result(envelope)
                else:
                    self._incoming.put_nowait(envelope)
        except ConnectionClosed:
            pass
        finally:
            self._incoming.put_nowait(None)
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("connection closed"))
