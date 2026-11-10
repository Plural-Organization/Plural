from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

Source = Literal["claude", "codex"]
Role = Literal["user", "assistant", "tool"]


class Turn(BaseModel):
    """One step of a foreign conversation, reduced to text. A tool call or its result is a short
    note, never a real call: the other agent's tools are not ours."""

    model_config = ConfigDict(frozen=True)

    role: Role
    text: str


class Candidate(BaseModel):
    """A session found on disk, before it is read in full."""

    model_config = ConfigDict(frozen=True)

    source: Source
    id: str
    path: Path
    title: str
    cwd: str | None
    updated_at: datetime
    turns: int


class ImportedSession(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: Source
    id: str
    title: str
    cwd: str | None
    branch: str | None
    turns: tuple[Turn, ...]
