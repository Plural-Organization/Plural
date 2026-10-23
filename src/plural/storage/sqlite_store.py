import asyncio
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any, Self

import aiosqlite

from plural.protocol.codec import EVENTS
from plural.protocol.events import Event, EventRecord
from plural.storage.migrations import migrate

_COLUMNS = "seq, id, ts, actor_id, payload"


class SqliteEventStore:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    @classmethod
    async def open(cls, path: Path) -> Self:
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        db = await aiosqlite.connect(path)
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=FULL")
        await migrate(db)
        return cls(db)

    async def append(
        self, event: Event, *, event_id: str, ts: datetime, actor_id: str | None
    ) -> EventRecord:
        cursor = await self._db.execute(
            "INSERT INTO events (id, ts, actor_id, type, payload) VALUES (?, ?, ?, ?, ?)",
            (event_id, ts.isoformat(), actor_id, event.type, event.model_dump_json()),
        )
        await self._db.commit()
        if cursor.lastrowid is None:
            raise RuntimeError("event was not stored")
        return EventRecord(seq=cursor.lastrowid, id=event_id, ts=ts, actor_id=actor_id, event=event)

    async def read(
        self, *, after: int = 0, before: int | None = None, limit: int | None = None
    ) -> list[EventRecord]:
        bound = -1 if limit is None else limit
        if before is None:
            rows = await self._db.execute_fetchall(
                f"SELECT {_COLUMNS} FROM events WHERE seq > ? ORDER BY seq LIMIT ?", (after, bound)
            )
            return _decode(rows)
        rows = await self._db.execute_fetchall(
            f"SELECT {_COLUMNS} FROM events WHERE seq > ? AND seq < ? ORDER BY seq DESC LIMIT ?",
            (after, before, bound),
        )
        return list(reversed(_decode(rows)))

    async def last_seq(self) -> int:
        cursor = await self._db.execute("SELECT COALESCE(MAX(seq), 0) FROM events")
        row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def close(self) -> None:
        await self._db.close()


def _decode(rows: Iterable[Any]) -> list[EventRecord]:
    return [
        EventRecord(
            seq=row[0],
            id=row[1],
            ts=datetime.fromisoformat(row[2]),
            actor_id=row[3],
            event=EVENTS.validate_json(row[4]),
        )
        for row in rows
    ]
