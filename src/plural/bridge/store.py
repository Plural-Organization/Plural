"""Who owns a bridge and which chat follows which room, kept in one private file."""

import json
import os
import secrets
from contextlib import suppress
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from plural.bridge.model import Person, Place


class _Link(BaseModel):
    room: str
    chat: str
    thread: str | None = None
    private: bool = False


class _Saved(BaseModel):
    owners: dict[str, str] = Field(default_factory=dict[str, str])
    pairing: str | None = None
    links: dict[str, _Link] = Field(default_factory=dict[str, _Link])


class BridgeStore:
    """`<data dir>/bridge/<platform>.json`, readable by its owner only.

    Owners are the people allowed to run the session from the chat: answer approvals, link and
    unlink chats, stop a run. Everyone else in a linked chat writes to the room as a guest.
    """

    def __init__(self, data_dir: Path, platform: str) -> None:
        self.platform = platform
        self.path = data_dir / "bridge" / f"{platform}.json"
        self._stamp = 0
        self._saved = self._load()

    def _fresh(self) -> None:
        """Another process may have paired or linked: read the file again when it changed."""
        try:
            stamp = self.path.stat().st_mtime_ns
        except OSError:
            return
        if stamp != self._stamp:
            self._saved = self._load()

    @property
    def owners(self) -> dict[str, str]:
        self._fresh()
        return dict(self._saved.owners)

    @property
    def rooms(self) -> set[str]:
        self._fresh()
        return {link.room for link in self._saved.links.values()}

    def is_owner(self, person: Person) -> bool:
        self._fresh()
        return person.id in self._saved.owners

    def pairing_code(self, *, renew: bool = False) -> str:
        self._fresh()
        if renew or self._saved.pairing is None:
            self._saved.pairing = f"{secrets.randbelow(10**6):06d}"
            self._save()
        return self._saved.pairing

    def pair(self, person: Person, code: str) -> bool:
        self._fresh()
        expected = self._saved.pairing
        if expected is None or not secrets.compare_digest(code.strip(), expected):
            return False
        self._saved.owners[person.id] = person.name
        self._saved.pairing = None
        self._save()
        return True

    def unpair(self, person_id: str) -> None:
        self._fresh()
        if self._saved.owners.pop(person_id, None) is not None:
            self._save()

    def places_of_all(self) -> list[Place]:
        self._fresh()
        return [
            Place(self.platform, link.chat, link.thread, link.private)
            for link in self._saved.links.values()
        ]

    def room_of(self, place: Place) -> str | None:
        self._fresh()
        link = self._saved.links.get(place.key)
        return None if link is None else link.room

    def places_of(self, room: str) -> list[Place]:
        self._fresh()
        return [
            Place(self.platform, link.chat, link.thread, link.private)
            for link in self._saved.links.values()
            if link.room == room
        ]

    def link(self, place: Place, room: str) -> None:
        self._fresh()
        self._saved.links[place.key] = _Link(
            room=room, chat=place.chat, thread=place.thread, private=place.private
        )
        self._save()

    def unlink(self, place: Place) -> str | None:
        self._fresh()
        link = self._saved.links.pop(place.key, None)
        if link is None:
            return None
        self._save()
        return link.room

    def _load(self) -> _Saved:
        with suppress(OSError):
            self._stamp = self.path.stat().st_mtime_ns
        try:
            return _Saved.model_validate_json(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return _Saved()
        except (OSError, ValidationError, json.JSONDecodeError) as error:
            raise ValueError(f"{self.path} is unreadable: {error}") from error

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.path.with_suffix(".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(self._saved.model_dump_json(indent=2))
        temporary.replace(self.path)
        self._stamp = self.path.stat().st_mtime_ns
