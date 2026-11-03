from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
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
    omitted_bytes: int = 0


@dataclass(frozen=True, slots=True)
class DirEntry:
    name: str
    is_dir: bool


OutputSink = Callable[[str], None]


class ExecutionBackend(Protocol):
    async def run(
        self,
        command: str,
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: float,
        on_output: OutputSink | None = None,
    ) -> ProcResult: ...

    async def read_file(self, path: Path) -> bytes: ...

    async def write_file(self, path: Path, data: bytes) -> None: ...

    async def list_dir(self, path: Path) -> list[DirEntry]: ...

    async def walk(self, root: Path, *, limit: int) -> list[Path]: ...


@dataclass(frozen=True, slots=True)
class Grant:
    """A folder outside the workspace the host opened for one call."""

    root: Path
    write: bool


@dataclass(frozen=True, slots=True)
class Workspace:
    root: Path
    grants: tuple[Grant, ...] = ()

    @classmethod
    def at(cls, path: Path) -> Self:
        return cls(path.expanduser().resolve(strict=True))

    def granting(self, folder: Path, *, write: bool) -> Self:
        return replace(self, grants=(*self.grants, Grant(folder, write)))

    def outside(self, raw: str) -> Path | None:
        """The folder a path needs opened, or None when it is inside the workspace or a grant."""
        candidate = (self.root / raw).resolve()
        if candidate.is_relative_to(self.root) or self._grant_for(candidate) is not None:
            return None
        return candidate if candidate.is_dir() else candidate.parent

    def resolve(self, raw: str, *, write: bool = False) -> Path:
        candidate = (self.root / raw).resolve()
        if candidate.is_relative_to(self.root):
            base = self.root
        else:
            grant = self._grant_for(candidate)
            if grant is None:
                raise PathOutsideWorkspace(f"{raw} is outside the workspace")
            if write and not grant.write:
                raise PathOutsideWorkspace(f"{raw} is open for reading only")
            base = grant.root
        if is_denied_path(candidate.relative_to(base)):
            raise PathDenied(f"{raw} is protected")
        return candidate

    def relative(self, path: Path) -> str:
        """The path from the workspace root, or the whole path for a folder opened outside it."""
        if path.is_relative_to(self.root):
            return path.relative_to(self.root).as_posix()
        return path.as_posix()

    def is_denied(self, path: Path) -> bool:
        if path.is_relative_to(self.root):
            return is_denied_path(path.relative_to(self.root))
        grant = self._grant_for(path)
        return grant is None or is_denied_path(path.relative_to(grant.root))

    def _grant_for(self, path: Path) -> Grant | None:
        return next((grant for grant in self.grants if path.is_relative_to(grant.root)), None)
