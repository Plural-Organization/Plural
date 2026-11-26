"""The session of a host that hands its room over, packed to travel and unpacked on the new host.

One gzip tarball: `manifest.json`, `session.db` (a consistent copy of the event log) and
`attachments/` (the files people attached). It is sealed to the successor before it leaves the old
host (`plural.security.seal`), so what carries it cannot read it."""

import hashlib
import io
import json
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, ValidationError

from plural.storage.sessions import ROOM_ID, session_path

MANIFEST: Final = "manifest.json"
DATABASE: Final = "session.db"
ATTACHMENTS: Final = "attachments"
# A transfer larger than this is a mistake or an attack, not a conversation.
MAX_UNPACKED_BYTES: Final = 2 * 1024 * 1024 * 1024
# Meta the new host starts its own: its link base, title and start are carried, its folder is not.
_DROPPED_META: Final = ("workspace", "host_name")


class HandoverError(Exception):
    pass


class RepoNote(BaseModel):
    """Where the old host's code was, so the new host can tell whether its own folder matches."""

    model_config = ConfigDict(frozen=True)

    repo_id: str | None = None
    branch: str | None = None
    head: str | None = None
    dirty: int | None = None


class HandoverManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    room: str
    last_seq: int
    # The old host's public key, which the new host trusts for the tokens that key signed.
    host_key: str
    host_name: str
    # The participant id the old host has from now on; its old one, `p_host`, is the new host's.
    former_host_id: str
    # The participant taking the seat: its id in the room, and the name it goes by.
    successor_id: str
    successor_name: str
    created_at: datetime
    database_sha256: str
    repo: RepoNote = RepoNote()


def pack(data_dir: Path, manifest: HandoverManifest) -> bytes:
    """The session, as it is on disk now, in one blob. Run it where the event store is idle."""
    source = session_path(data_dir, manifest.room)
    if not source.exists():
        raise HandoverError(f"there is no session {manifest.room}")
    with tempfile.TemporaryDirectory(prefix="plural-handover-") as scratch:
        copy = Path(scratch) / DATABASE
        reader = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
        writer = sqlite3.connect(copy)
        try:
            # The backup API copies a database another connection is writing to, WAL and all.
            reader.backup(writer)
        finally:
            writer.close()
            reader.close()
        measured = manifest.model_copy(update={"database_sha256": _sha256(copy)})
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode="w:gz") as archive:
            body = measured.model_dump_json().encode()
            info = tarfile.TarInfo(MANIFEST)
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
            archive.add(copy, arcname=DATABASE)
            attached = data_dir.expanduser() / ATTACHMENTS / manifest.room
            if attached.is_dir():
                for path in sorted(attached.iterdir()):
                    if path.is_file():
                        archive.add(path, arcname=f"{ATTACHMENTS}/{path.name}")
    return out.getvalue()


def unpack(data_dir: Path, blob: bytes) -> HandoverManifest:
    """Puts a packed session where this host keeps its sessions. Refuses one it already has."""
    with tempfile.TemporaryDirectory(prefix="plural-handover-") as scratch:
        root = Path(scratch)
        total = 0
        try:
            with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
                for member in archive:
                    _check(member)
                    total += member.size
                    if total > MAX_UNPACKED_BYTES:
                        raise HandoverError("the transfer is too large")
                    archive.extract(member, root, filter="data")
        except (tarfile.TarError, OSError) as error:
            raise HandoverError(f"the transfer is not a session: {error}") from error
        try:
            manifest = HandoverManifest.model_validate_json((root / MANIFEST).read_bytes())
        except (OSError, ValidationError) as error:
            raise HandoverError("the transfer has no usable manifest") from error
        if ROOM_ID.fullmatch(manifest.room) is None:
            raise HandoverError("the transfer names a session id that is not one")
        database = root / DATABASE
        if not database.exists() or _sha256(database) != manifest.database_sha256:
            raise HandoverError("the event log did not arrive intact")
        target = session_path(data_dir, manifest.room)
        if target.exists():
            raise HandoverError(f"this computer already has the session {manifest.room}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(database, target)
        _forget_the_old_machine(target)
        attached = root / ATTACHMENTS
        if attached.is_dir():
            shutil.copytree(attached, data_dir.expanduser() / ATTACHMENTS / manifest.room)
    return manifest


def _check(member: tarfile.TarInfo) -> None:
    """Only the three things a pack holds, none of them a link or outside the folder."""
    parts = Path(member.name).parts
    allowed = member.name in {MANIFEST, DATABASE} or (
        len(parts) == 2 and parts[0] == ATTACHMENTS and parts[1] not in {"", ".", ".."}
    )
    if not (member.isfile() or member.isdir()) or Path(member.name).is_absolute() or not allowed:
        raise HandoverError(f"the transfer holds something it should not: {member.name}")


def _forget_the_old_machine(path: Path) -> None:
    db = sqlite3.connect(path)
    try:
        db.executemany("DELETE FROM meta WHERE key = ?", [(key,) for key in _DROPPED_META])
        db.commit()
    finally:
        db.close()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def describe(manifest: HandoverManifest) -> str:
    return json.dumps(manifest.model_dump(mode="json"), sort_keys=True)
