from importlib import resources

import aiosqlite


async def migrate(db: aiosqlite.Connection) -> None:
    await db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    cursor = await db.execute("SELECT value FROM meta WHERE key = 'schema_version'")
    row = await cursor.fetchone()
    current = int(row[0]) if row else 0
    for version, script in _scripts():
        if version <= current:
            continue
        await db.executescript(script)
        await db.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(version),),
        )
    await db.commit()


def _scripts() -> list[tuple[int, str]]:
    files = resources.files(__package__)
    scripts = [
        (int(entry.name.split("_", 1)[0]), entry.read_text(encoding="utf-8"))
        for entry in files.iterdir()
        if entry.name.endswith(".sql")
    ]
    return sorted(scripts)
