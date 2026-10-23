from datetime import UTC, datetime
from pathlib import Path

from plural.protocol.events import ParticipantLeft
from plural.storage.jsonl_export import export_jsonl
from plural.storage.sqlite_store import SqliteEventStore

TS = datetime(2026, 10, 22, tzinfo=UTC)


async def test_append_read_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / "s.db"
    store = await SqliteEventStore.open(path)
    for i in range(5):
        record = await store.append(
            ParticipantLeft(participant_id=f"p_{i}"), event_id=f"e_{i}", ts=TS, actor_id=None
        )
        assert record.seq == i + 1
    assert [r.seq for r in await store.read(after=3)] == [4, 5]
    assert [r.seq for r in await store.read(before=5, limit=2)] == [3, 4]
    await store.close()

    reopened = await SqliteEventStore.open(path)
    assert await reopened.last_seq() == 5
    assert await export_jsonl(reopened, tmp_path / "out.jsonl") == 5
    await reopened.close()
