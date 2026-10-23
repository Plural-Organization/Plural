from datetime import datetime
from typing import Protocol

from plural.protocol.events import Event, EventRecord


class EventStore(Protocol):
    async def append(
        self, event: Event, *, event_id: str, ts: datetime, actor_id: str | None
    ) -> EventRecord: ...

    async def read(
        self, *, after: int = 0, before: int | None = None, limit: int | None = None
    ) -> list[EventRecord]: ...

    async def last_seq(self) -> int: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def new(self, prefix: str) -> str: ...
