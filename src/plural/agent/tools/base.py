import asyncio
import hashlib
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, JsonValue

from plural.agent.providers.base import ToolSchema
from plural.agent.sandbox.base import ExecutionBackend, Workspace
from plural.protocol.models import Provenance, ToolRisk


class ToolError(Exception):
    pass


class ToolArgs(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


@dataclass(frozen=True, slots=True)
class ToolResult:
    content: str
    is_error: bool = False
    diff: str | None = None


class FileLocks:
    def __init__(self) -> None:
        self._locks: dict[Path, asyncio.Lock] = {}

    def __call__(self, path: Path) -> asyncio.Lock:
        return self._locks.setdefault(path, asyncio.Lock())


class FileStamps:
    def __init__(self) -> None:
        self._seen: dict[Path, str] = {}

    def record(self, path: Path, data: bytes) -> None:
        self._seen[path] = hashlib.sha256(data).hexdigest()

    def check(self, path: Path, data: bytes | None) -> None:
        seen = self._seen.get(path)
        if seen is None or data is None or hashlib.sha256(data).hexdigest() == seen:
            return
        raise ToolError(
            f"{path.name} changed since you last read it, possibly by someone in the session. "
            "Read it again before changing it"
        )


def _discard(_text: str) -> None:
    return None


@dataclass(frozen=True, slots=True)
class ToolCtx:
    workspace: Workspace
    backend: ExecutionBackend
    locks: FileLocks = field(default_factory=FileLocks)
    stamps: FileStamps = field(default_factory=FileStamps)
    emit: Callable[[str], None] = _discard
    provenance: Provenance | None = None
    cancel: asyncio.Event | None = None


@dataclass(frozen=True, slots=True)
class PreparedCall:
    name: str
    risk: ToolRisk
    subject: str
    execute: Callable[[ToolCtx], Awaitable[ToolResult]]


@dataclass(frozen=True, slots=True)
class ToolSpec[A: ToolArgs]:
    name: str
    description: str
    risk: ToolRisk
    args_model: type[A]


class Tool(Protocol):
    @property
    def name(self) -> str: ...

    def schema(self) -> ToolSchema: ...

    def prepare(self, raw: Mapping[str, JsonValue]) -> PreparedCall: ...


class TypedTool[A: ToolArgs](ABC):
    spec: ToolSpec[A]

    @property
    def name(self) -> str:
        return self.spec.name

    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.spec.name,
            description=self.spec.description,
            parameters=self.spec.args_model.model_json_schema(),
        )

    def prepare(self, raw: Mapping[str, JsonValue]) -> PreparedCall:
        args = self.spec.args_model.model_validate(raw)
        return PreparedCall(
            name=self.spec.name,
            risk=self.spec.risk,
            subject=self.subject(args),
            execute=lambda ctx: self.run(args, ctx),
        )

    @abstractmethod
    def subject(self, args: A) -> str: ...

    @abstractmethod
    async def run(self, args: A, ctx: ToolCtx) -> ToolResult: ...
