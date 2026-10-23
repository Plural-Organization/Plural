from datetime import datetime

from pydantic import JsonValue, TypeAdapter

from plural.protocol.commands import Command
from plural.protocol.envelope import PROTOCOL_VERSION, Envelope, ErrorCode, ErrorInfo, Kind
from plural.protocol.events import Event, EventRecord
from plural.protocol.models import Model

COMMANDS: TypeAdapter[Command] = TypeAdapter(Command)
EVENTS: TypeAdapter[Event] = TypeAdapter(Event)


class ProtocolError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code

    def info(self) -> ErrorInfo:
        return ErrorInfo(code=self.code, message=str(self))


def decode_command(envelope: Envelope) -> Command:
    _expect(envelope, Kind.CMD)
    return COMMANDS.validate_python({**envelope.payload, "type": envelope.type})


def decode_event(envelope: Envelope) -> Event:
    _expect(envelope, Kind.EVT)
    return EVENTS.validate_python({**envelope.payload, "type": envelope.type})


def decode_record(envelope: Envelope) -> EventRecord | None:
    if envelope.seq is None:
        return None
    return EventRecord(
        seq=envelope.seq,
        id=envelope.id,
        ts=envelope.ts,
        actor_id=envelope.actor,
        event=decode_event(envelope),
    )


def encode_command(
    command: Command, *, envelope_id: str, room: str, ts: datetime, token: str | None
) -> Envelope:
    return Envelope(
        id=envelope_id,
        kind=Kind.CMD,
        type=command.type,
        room=room,
        ts=ts,
        token=token,
        payload=_payload(command),
    )


def encode_event(
    event: Event,
    *,
    envelope_id: str,
    room: str,
    ts: datetime,
    actor: str | None = None,
    to: str | None = None,
) -> Envelope:
    return Envelope(
        id=envelope_id,
        kind=Kind.EVT,
        type=event.type,
        room=room,
        ts=ts,
        actor=actor,
        to=to,
        payload=_payload(event),
    )


def encode_record(record: EventRecord, *, room: str, to: str | None = None) -> Envelope:
    return Envelope(
        id=record.id,
        kind=Kind.EVT,
        type=record.event.type,
        room=room,
        ts=record.ts,
        actor=record.actor_id,
        seq=record.seq,
        to=to,
        payload=_payload(record.event),
    )


def encode_ack(
    re: str, *, envelope_id: str, room: str, ts: datetime, error: ErrorInfo | None = None
) -> Envelope:
    return Envelope(
        id=envelope_id, kind=Kind.ACK, room=room, ts=ts, re=re, ok=error is None, error=error
    )


def _expect(envelope: Envelope, kind: Kind) -> None:
    if envelope.v != PROTOCOL_VERSION:
        raise ProtocolError(
            ErrorCode.VERSION_MISMATCH, f"expected v{PROTOCOL_VERSION}, got v{envelope.v}"
        )
    if envelope.kind is not kind:
        raise ProtocolError(ErrorCode.INVALID, f"expected {kind}, got {envelope.kind}")


def _payload(model: Model) -> dict[str, JsonValue]:
    return model.model_dump(mode="json", exclude={"type"})
