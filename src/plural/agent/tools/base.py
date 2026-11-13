import asyncio
import hashlib
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast

from pydantic import BaseModel, ConfigDict, JsonValue

from plural.agent.providers.base import ToolSchema
from plural.agent.sandbox.base import ExecutionBackend, Workspace
from plural.agent.tools.truncation import FullOutputs
from plural.agent.tracing import Span
from plural.protocol.models import Provenance, ToolRisk


class ToolError(Exception):
    pass


class ToolArgs(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def args_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The JSON schema of a tool's arguments, without the titles pydantic adds: they repeat the
    names and cost the model tokens on every request."""
    return _untitled(model.model_json_schema())


def _untitled(node: Any) -> Any:
    if isinstance(node, dict):
        items = cast("dict[str, Any]", node).items()
        return {
            key: _untitled(value)
            for key, value in items
            if not (key == "title" and isinstance(value, str))
        }
    if isinstance(node, list):
        return [_untitled(value) for value in cast("list[Any]", node)]
    return node


@dataclass(frozen=True, slots=True)
class ToolResult:
    content: str
    is_error: bool = False
    diff: str | None = None
    terminate: bool = False


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
    outputs: FullOutputs = field(default_factory=FullOutputs)
    emit: Callable[[str], None] = _discard
    provenance: Provenance | None = None
    cancel: asyncio.Event | None = None
    # The span of the call being run, for a tool that does traced work of its own.
    span: Span | None = None


@dataclass(frozen=True, slots=True)
class Reach:
    """The path a file tool is about to touch, and whether it changes it."""

    path: str
    write: bool


@dataclass(frozen=True, slots=True)
class PreparedCall:
    name: str
    risk: ToolRisk
    subject: str
    execute: Callable[[ToolCtx], Awaitable[ToolResult]]
    reach: Reach | None = None


@dataclass(frozen=True, slots=True)
class ToolSpec[A: ToolArgs]:
    name: str
    description: str
    risk: ToolRisk
    args_model: type[A]
    # Rules for the system prompt, there only while the tool is declared on every request.
    guidelines: tuple[str, ...] = ()


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

    @property
    def guidelines(self) -> tuple[str, ...]:
        return self.spec.guidelines

    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.spec.name,
            description=self.spec.description,
            parameters=args_schema(self.spec.args_model),
        )

    def prepare(self, raw: Mapping[str, JsonValue]) -> PreparedCall:
        args = self.spec.args_model.model_validate(raw)
        return PreparedCall(
            name=self.spec.name,
            risk=self.spec.risk,
            subject=self.subject(args),
            execute=lambda ctx: self.run(args, ctx),
            reach=self.reach(args),
        )

    def reach(self, args: A) -> Reach | None:
        """The path the tool touches: a path outside the workspace has to be opened by the host."""
        return None

    @abstractmethod
    def subject(self, args: A) -> str: ...

    @abstractmethod
    async def run(self, args: A, ctx: ToolCtx) -> ToolResult: ...
