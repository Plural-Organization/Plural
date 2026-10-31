import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict

ROOM_ID: Final = re.compile(r"^r_[0-9A-Za-z_-]{4,64}$")
TITLE_CHARS: Final = 80


class SessionInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    room: str
    title: str
    workspace: str | None
    host_name: str | None
    team: str | None = None
    created_at: datetime
    updated_at: datetime
    prompts: int
    people: int


def sessions_dir(data_dir: Path) -> Path:
    return data_dir.expanduser() / "sessions"


def session_path(data_dir: Path, room: str) -> Path:
    if ROOM_ID.fullmatch(room) is None:
        raise ValueError(f"{room!r} is not a session id")
    return sessions_dir(data_dir) / f"{room}.db"


def _one_line(text: str) -> str:
    line = next((entry.strip() for entry in text.splitlines() if entry.strip()), "")
    return line if len(line) <= TITLE_CHARS else f"{line[: TITLE_CHARS - 1]}…"


def _scalar(db: sqlite3.Connection, query: str, *arguments: object) -> object:
    row = db.execute(query, arguments).fetchone()
    return row[0] if row else None


def read_session(path: Path) -> SessionInfo | None:
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        meta = dict(db.execute("SELECT key, value FROM meta").fetchall())
        first = _scalar(db, "SELECT ts FROM events ORDER BY seq LIMIT 1")
        last = _scalar(db, "SELECT ts FROM events ORDER BY seq DESC LIMIT 1")
        if not isinstance(first, str) or not isinstance(last, str):
            return None
        prompt = _scalar(
            db,
            "SELECT json_extract(payload, '$.text') FROM events "
            "WHERE type = 'prompt.accepted' ORDER BY seq LIMIT 1",
        )
        prompts = _scalar(db, "SELECT COUNT(*) FROM events WHERE type = 'prompt.accepted'")
        people = _scalar(
            db,
            "SELECT COUNT(DISTINCT json_extract(payload, '$.participant.id')) FROM events "
            "WHERE type = 'participant.joined'",
        )
        title = meta.get("title") or (_one_line(prompt) if isinstance(prompt, str) else "")
        return SessionInfo(
            room=path.stem,
            title=title or "(no prompt yet)",
            workspace=meta.get("workspace"),
            host_name=meta.get("host_name"),
            team=meta.get("team") or None,
            created_at=datetime.fromisoformat(meta.get("created_at") or first),
            updated_at=datetime.fromisoformat(last),
            prompts=int(prompts) if isinstance(prompts, int) else 0,
            people=int(people) if isinstance(people, int) else 0,
        )
    except (sqlite3.Error, ValueError):
        return None
    finally:
        db.close()


def list_sessions(data_dir: Path, *, workspace: Path | None = None) -> list[SessionInfo]:
    folder = sessions_dir(data_dir)
    if not folder.is_dir():
        return []
    found = [info for path in folder.glob("r_*.db") if (info := read_session(path)) is not None]
    if workspace is not None:
        wanted = str(workspace.expanduser().resolve())
        found = [info for info in found if info.workspace == wanted]
    return sorted(found, key=lambda info: info.updated_at, reverse=True)


def delete_session(data_dir: Path, room: str) -> bool:
    path = session_path(data_dir, room)
    removed = False
    for suffix in ("", "-wal", "-shm"):
        target = path.with_name(path.name + suffix)
        if target.exists():
            target.unlink()
            removed = True
    return removed
