from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, Self

from plural.security.secrets import is_denied_path

IGNORED_DIRECTORIES: Final = frozenset(
    {".git", ".hg", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".ruff_cache", ".plural"}
)


class SandboxError(Exception):
    pass


class PathOutsideWorkspace(SandboxError):
    pass


class PathDenied(SandboxError):
    pass


@dataclass(frozen=True, slots=True)
class ProcResult:
    exit_code: int
    output: str
    timed_out: bool = False


@dataclass(frozen=True, slots=True)
class DirEntry:
    name: str
    is_dir: bool


class ExecutionBackend(Protocol):
    async def run(
        self, command: str, *, cwd: Path, env: Mapping[str, str], timeout: float
    ) -> ProcResult: ...

    async def read_file(self, path: Path) -> bytes: ...

    async def write_file(self, path: Path, data: bytes) -> None: ...

    async def list_dir(self, path: Path) -> list[DirEntry]: ...

    async def walk(self, root: Path, *, limit: int) -> list[Path]: ...


@dataclass(frozen=True, slots=True)
class Workspace:
    root: Path

    @classmethod
    def at(cls, path: Path) -> Self:
        return cls(path.expanduser().resolve(strict=True))

    def resolve(self, raw: str) -> Path:
        candidate = (self.root / raw).resolve()
        if not candidate.is_relative_to(self.root):
            raise PathOutsideWorkspace(f"{raw} is outside the workspace")
        if self.is_denied(candidate):
            raise PathDenied(f"{raw} is protected")
        return candidate

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def is_denied(self, path: Path) -> bool:
        return is_denied_path(path.relative_to(self.root))
