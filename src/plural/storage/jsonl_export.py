import asyncio
from pathlib import Path

from plural.core.ports import EventStore


async def export_jsonl(store: EventStore, destination: Path) -> int:
    records = await store.read()
    body = "".join(f"{record.model_dump_json()}\n" for record in records)
    await asyncio.to_thread(destination.write_text, body, encoding="utf-8")
    return len(records)
