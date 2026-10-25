import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Final, Self
from urllib.parse import parse_qs, urlsplit, urlunsplit

from pydantic import ValidationError
from websockets.exceptions import WebSocketException

from plural.client.connection import CommandRejected, Wire
from plural.client.projection import Projection
from plural.protocol.codec import ProtocolError, decode_event, decode_record
from plural.protocol.commands import ClientInfo, Command, SessionHello
from plural.protocol.envelope import Envelope, ErrorCode
from plural.protocol.events import Event, SessionSnapshot, SessionWelcome

INITIAL_DELAY_S: Final = 0.25
MAX_DELAY_S: Final = 2.0
FATAL: Final = frozenset({ErrorCode.UNAUTHORIZED, ErrorCode.FORBIDDEN, ErrorCode.VERSION_MISMATCH})


@dataclass(frozen=True, slots=True)
class JoinLink:
    url: str
    room: str
    invite: str | None = None
    token: str | None = None

    @classmethod
    def parse(cls, raw: str) -> Self:
        parts = urlsplit(raw)
        if parts.scheme not in {"ws", "wss"}:
            raise ValueError("link must start with ws:// or wss://")
        room = parts.path.rstrip("/").rsplit("/", 1)[-1]
        if not room:
            raise ValueError("link has no room")
        query = parse_qs(parts.query)
        return cls(
            url=urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")),
            room=room,
            invite=query.get("invite", [None])[0],
            token=query.get("token", [None])[0],
        )


class SessionClient:
    def __init__(self, link: JoinLink, *, name: str, client: ClientInfo) -> None:
        self.projection = Projection()
        self._link = link
        self._name = name
        self._client = client
        self._token = link.token
        self._wire: Wire | None = None

    async def send(self, command: Command) -> None:
        if self._wire is None:
            raise ConnectionError("not connected")
        await self._wire.request(command, token=self._token)

    async def events(self) -> AsyncIterator[Event]:
        delay = INITIAL_DELAY_S
        while True:
            try:
                async with await Wire.open(self._link.url, room=self._link.room) as wire:
                    await wire.request(self._hello(), token=None)
                    self._wire = wire
                    delay = INITIAL_DELAY_S
                    async for envelope in wire.envelopes():
                        event = self._absorb(envelope)
                        if event is not None:
                            yield event
            except CommandRejected as error:
                if error.error.code in FATAL:
                    raise
            except (OSError, TimeoutError, WebSocketException):
                pass
            finally:
                self._wire = None
            await asyncio.sleep(delay)
            delay = min(delay * 2, MAX_DELAY_S)

    def _hello(self) -> SessionHello:
        return SessionHello(
            client=self._client,
            name=self._name,
            invite=None if self._token else self._link.invite,
            token=self._token,
            since=self.projection.state.last_seq if self.projection.ready else None,
        )

    def _absorb(self, envelope: Envelope) -> Event | None:
        try:
            record = decode_record(envelope)
            event = record.event if record else decode_event(envelope)
        except (ValidationError, ProtocolError):
            return None
        if record is not None:
            return event if self.projection.apply(record) else None
        match event:
            case SessionWelcome(token=token, participant=participant, base_policy=base):
                self._token = token
                self.projection.me_id = participant.id
                self.projection.base_policy = base
            case SessionSnapshot(state=state, streaming=streaming):
                self.projection.load(state, streaming)
            case _:
                self.projection.observe(event)
        return event
