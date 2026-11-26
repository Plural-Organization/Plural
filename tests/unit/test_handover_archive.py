import io
import sqlite3
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from plural.host.config import HostSettings
from plural.host.takeover import Takeover
from plural.storage.handover import (
    HandoverError,
    HandoverManifest,
    RepoNote,
    pack,
    unpack,
)
from plural.storage.sessions import session_path

NOW = datetime(2026, 11, 26, tzinfo=UTC)
ROOM = "r_handover1"


def manifest(**over: object) -> HandoverManifest:
    fields: dict[str, object] = {
        "room": ROOM,
        "last_seq": 3,
        "host_key": "key-a",
        "host_name": "Bob",
        "former_host_id": "p_bob",
        "successor_id": "p_alia",
        "successor_name": "Alia",
        "created_at": NOW,
        "database_sha256": "",
        "repo": RepoNote(repo_id="github.com/acme/app", branch="main", head="abc1234", dirty=0),
    }
    return HandoverManifest(**{**fields, **over})  # type: ignore[arg-type]


def make_session(data: Path, room: str = ROOM) -> None:
    path = session_path(data, room)
    path.parent.mkdir(parents=True)
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE events (seq INTEGER PRIMARY KEY, payload TEXT)")
    db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    db.executemany("INSERT INTO events (payload) VALUES (?)", [("one",), ("two",), ("three",)])
    db.executemany(
        "INSERT INTO meta VALUES (?, ?)",
        [("room_link", "secret-code"), ("workspace", "/home/bob/app"), ("host_name", "Bob")],
    )
    db.commit()
    attached = data / "attachments" / room
    attached.mkdir(parents=True)
    (attached / "a1.txt").write_text("a file someone attached")
    # The connection stays open and the log is mid-WAL, as it is on a running host.
    make_session.open = db  # type: ignore[attr-defined]


def test_a_session_travels_with_its_log_its_files_and_its_link(tmp_path: Path) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    make_session(old)
    arrived = unpack(new, pack(old, manifest()))
    assert arrived.room == ROOM
    assert arrived.repo.head == "abc1234"
    db = sqlite3.connect(session_path(new, ROOM))
    assert [row[0] for row in db.execute("SELECT payload FROM events ORDER BY seq")] == [
        "one",
        "two",
        "three",
    ]
    meta = dict(db.execute("SELECT key, value FROM meta").fetchall())
    # The room link goes along, so the invite everyone holds still works; the old folder does not.
    assert meta == {"room_link": "secret-code"}
    assert (new / "attachments" / ROOM / "a1.txt").read_text() == "a file someone attached"


def test_a_computer_that_has_the_session_does_not_take_it_twice(tmp_path: Path) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    make_session(old)
    blob = pack(old, manifest())
    unpack(new, blob)
    with pytest.raises(HandoverError, match="already has"):
        unpack(new, blob)


def test_a_log_that_changed_on_the_way_is_refused(tmp_path: Path) -> None:
    old = tmp_path / "old"
    make_session(old)
    blob = pack(old, manifest())
    out = io.BytesIO()
    with (
        tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as source,
        tarfile.open(fileobj=out, mode="w:gz") as bent,
    ):
        for member in source:
            data = source.extractfile(member)
            body = data.read() if data else b""
            if member.name == "session.db":
                body = body[:-1] + bytes([body[-1] ^ 1])
            member.size = len(body)
            bent.addfile(member, io.BytesIO(body))
    with pytest.raises(HandoverError, match="intact"):
        unpack(tmp_path / "new", out.getvalue())


@pytest.mark.parametrize("name", ["../escape", "/etc/passwd", "attachments/../../x", "other.txt"])
def test_a_pack_that_reaches_outside_its_folder_is_refused(tmp_path: Path, name: str) -> None:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as bad:
        info = tarfile.TarInfo(name)
        info.size = 1
        bad.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(HandoverError):
        unpack(tmp_path / "new", out.getvalue())
    assert not (tmp_path / "escape").exists()


def test_a_blob_that_is_not_a_tarball_is_refused(tmp_path: Path) -> None:
    with pytest.raises(HandoverError):
        unpack(tmp_path / "new", b"not a tarball")


def test_packing_a_session_that_is_not_there_says_so(tmp_path: Path) -> None:
    with pytest.raises(HandoverError, match="no session"):
        pack(tmp_path, manifest())


def committed_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "ws"
    folder.mkdir()
    git = ["git", "-C", str(folder), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], check=True)
    (folder / "a.txt").write_text("a")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "one"], check=True)
    return folder


async def test_a_takeover_tells_how_the_new_folder_differs_from_the_old_one(tmp_path: Path) -> None:
    folder = committed_folder(tmp_path)
    takeover = Takeover(
        "ws://127.0.0.1:1/r_x?token=t", HostSettings(workspace=folder, data_dir=tmp_path / "d")
    )
    elsewhere = manifest(repo=RepoNote(repo_id="github.com/acme/app", head="abc1234", dirty=2))
    notes = await takeover.compare(elsewhere)
    # This folder has no remote, so it is not the same repository as the one the session was in.
    assert any("github.com/acme/app" in note for note in notes)
    assert any("2 uncommitted" in note for note in notes)
    assert await takeover.compare(manifest(repo=RepoNote())) == []
