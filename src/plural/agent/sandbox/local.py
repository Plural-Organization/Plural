import asyncio
import os
import signal
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path

from plural.agent.sandbox.base import IGNORED_DIRECTORIES, DirEntry, ProcResult


class LocalBackend:
    async def run(
        self, command: str, *, cwd: Path, env: Mapping[str, str], timeout: float
    ) -> ProcResult:
        process = await asyncio.create_subprocess_exec(
            "bash",
            "-lc",
            command,
            cwd=cwd,
            env=dict(env),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout)
        except TimeoutError:
            _kill_group(process)
            await process.wait()
            return ProcResult(exit_code=-signal.SIGKILL, output="", timed_out=True)
        except asyncio.CancelledError:
            _kill_group(process)
            raise
        return ProcResult(exit_code=process.returncode or 0, output=output.decode(errors="replace"))

    async def read_file(self, path: Path) -> bytes:
        return await asyncio.to_thread(path.read_bytes)

    async def write_file(self, path: Path, data: bytes) -> None:
        await asyncio.to_thread(_write, path, data)

    async def list_dir(self, path: Path) -> list[DirEntry]:
        return await asyncio.to_thread(_list_dir, path)

    async def walk(self, root: Path, *, limit: int) -> list[Path]:
        return await asyncio.to_thread(_walk, root, limit)


def _kill_group(process: asyncio.subprocess.Process) -> None:
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _list_dir(path: Path) -> list[DirEntry]:
    return sorted(
        (DirEntry(name=p.name, is_dir=p.is_dir()) for p in path.iterdir()), key=lambda e: e.name
    )


def _walk(root: Path, limit: int) -> list[Path]:
    if root.is_file():
        return [root]
    found: list[Path] = []
    for current, directories, files in os.walk(root):
        directories[:] = sorted(d for d in directories if d not in IGNORED_DIRECTORIES)
        for name in sorted(files):
            found.append(Path(current, name))
            if len(found) >= limit:
                return found
    return found
