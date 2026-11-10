from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from plural.importers import claude
from plural.importers.model import Candidate, ImportedSession, Source
from plural.importers.render import NAMES, render


class ImportNotFound(Exception):
    """There is no such session to bring in. The message says why, for the person to read."""


class Imported(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    as_of: int
    text: str
    title: str
    updated_at: datetime | None = None


SOURCES: tuple[Source, ...] = ("claude",)


def candidates(folder: Path, kind: str, *, home: Path | None = None) -> list[Candidate]:
    if kind == "claude":
        return claude.find(folder, home=home)
    raise ImportNotFound(f"{kind!r} is not a source to import from yet. Try: claude")


def bring_in(spec: str, folder: Path, *, home: Path | None = None) -> Imported:
    """`claude` is the newest Claude Code session kept for this folder; `claude:ab12` the one
    whose id starts with ab12."""
    name, _, wanted = spec.partition(":")
    found = candidates(folder, name, home=home)
    kind: Source = "claude" if name == "claude" else "codex"
    if not found:
        raise ImportNotFound(f"there is no {NAMES[kind]} session for {folder}")
    chosen = found[0]
    if wanted:
        matching = [entry for entry in found if entry.id.startswith(wanted)]
        if len(matching) != 1:
            raise ImportNotFound(
                f"{len(matching)} {NAMES[kind]} sessions start with {wanted!r} in {folder}"
            )
        chosen = matching[0]
    session: ImportedSession | None = claude.read(chosen.path)
    if session is None:
        raise ImportNotFound(f"the session {chosen.id} has no conversation in it")
    return Imported(
        source=f"{NAMES[kind]} {chosen.id[:8]}",
        as_of=len(session.turns),
        text=render(session),
        title=session.title,
        updated_at=chosen.updated_at,
    )
