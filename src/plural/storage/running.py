"""Writes and reads the files of rooms served on this computer (protocol/running.py)."""

import os
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from plural.protocol.running import RunningRoom

FOLDER = "running"


def running_dir(data_dir: Path) -> Path:
    return data_dir / FOLDER


def announce(data_dir: Path, *, room: str, host_link: str, workspace: Path) -> Path:
    folder = running_dir(data_dir)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / f"{room}.json"
    entry = RunningRoom(
        room=room,
        host_link=host_link,
        workspace=str(workspace),
        pid=os.getpid(),
        started_at=datetime.now(UTC),
    )
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(entry.model_dump_json())
    temporary.replace(path)
    return path


def withdraw(path: Path) -> None:
    """Removes the file, unless another host has taken the room over since."""
    with suppress(OSError, ValidationError):
        entry = RunningRoom.model_validate_json(path.read_text(encoding="utf-8"))
        if entry.pid == os.getpid():
            path.unlink()


def running_rooms(data_dir: Path) -> list[RunningRoom]:
    """The rooms whose host is still alive, newest first. A stale file is removed."""
    rooms: list[RunningRoom] = []
    for path in sorted(running_dir(data_dir).glob("*.json")):
        try:
            entry = RunningRoom.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError):
            continue
        if not _alive(entry.pid):
            with suppress(OSError):
                path.unlink()
            continue
        rooms.append(entry)
    rooms.sort(key=lambda entry: entry.started_at, reverse=True)
    return rooms


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
