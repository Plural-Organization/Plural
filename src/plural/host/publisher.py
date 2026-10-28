from plural.core.ports import Clock, IdGenerator
from plural.core.visibility import record_visible_to
from plural.host.transport.base import Connection
from plural.protocol.codec import encode_ack, encode_event, encode_record
from plural.protocol.envelope import ErrorInfo
from plural.protocol.events import Event, EventRecord


class Publisher:
    def __init__(self, *, room: str, ids: IdGenerator, clock: Clock) -> None:
        self._room = room
        self._ids = ids
        self._clock = clock
        self._bound: dict[str, tuple[Connection, str]] = {}

    @property
    def room(self) -> str:
        return self._room

    def bind(self, connection: Connection, participant_id: str) -> None:
        self._bound[connection.id] = (connection, participant_id)

    def unbind(self, connection: Connection) -> str | None:
        entry = self._bound.pop(connection.id, None)
        return entry[1] if entry else None

    def participant_of(self, connection: Connection) -> str | None:
        entry = self._bound.get(connection.id)
        return entry[1] if entry else None

    def is_online(self, participant_id: str) -> bool:
        return any(pid == participant_id for _, pid in self._bound.values())

    def publish(self, record: EventRecord) -> None:
        envelope = encode_record(record, room=self._room)
        for connection, participant_id in self._bound.values():
            if record_visible_to(record, participant_id):
                connection.send(envelope)

    def publish_transient(self, event: Event, *, actor_id: str | None = None) -> None:
        envelope = encode_event(
            event,
            envelope_id=self._ids.new("e_"),
            room=self._room,
            ts=self._clock.now(),
            actor=actor_id,
        )
        for connection, _ in self._bound.values():
            connection.send(envelope)

    def deliver(self, connection: Connection, event: Event) -> None:
        envelope = encode_event(
            event,
            envelope_id=self._ids.new("e_"),
            room=self._room,
            ts=self._clock.now(),
            to=self.participant_of(connection),
        )
        connection.send(envelope)

    def deliver_record(self, connection: Connection, record: EventRecord) -> None:
        recipient = self.participant_of(connection)
        if recipient is not None and not record_visible_to(record, recipient):
            return
        connection.send(encode_record(record, room=self._room, to=recipient))

    def ack(self, connection: Connection, re: str, error: ErrorInfo | None = None) -> None:
        connection.send(
            encode_ack(
                re,
                envelope_id=self._ids.new("e_"),
                room=self._room,
                ts=self._clock.now(),
                error=error,
            )
        )

    def disconnect(self, participant_id: str, reason: str) -> None:
        for connection_id, (connection, pid) in list(self._bound.items()):
            if pid == participant_id:
                del self._bound[connection_id]
                connection.close(reason)
