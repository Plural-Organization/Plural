import asyncio
import codecs
import os
import signal
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path

from plural.agent.sandbox.base import IGNORED_DIRECTORIES, DirEntry, OutputSink, ProcResult


class LocalBackend:
    async def run(
        self,
        command: str,
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: float,
        on_output: OutputSink | None = None,
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
        collected: list[str] = []
        try:
            await asyncio.wait_for(_collect(process, collected, on_output), timeout)
        except TimeoutError:
            _kill_group(process)
            await process.wait()
            return ProcResult(exit_code=-signal.SIGKILL, output="", timed_out=True)
        except asyncio.CancelledError:
            _kill_group(process)
            raise
        return ProcResult(exit_code=process.returncode or 0, output="".join(collected))

    async def read_file(self, path: Path) -> bytes:
        return await asyncio.to_thread(path.read_bytes)

    async def write_file(self, path: Path, data: bytes) -> None:
        await asyncio.to_thread(_write, path, data)

    async def list_dir(self, path: Path) -> list[DirEntry]:
        return await asyncio.to_thread(_list_dir, path)

    async def walk(self, root: Path, *, limit: int) -> list[Path]:
        return await asyncio.to_thread(_walk, root, limit)


async def _collect(
    process: asyncio.subprocess.Process, collected: list[str], on_output: OutputSink | None
) -> None:
    assert process.stdout is not None
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    while chunk := await process.stdout.read(4096):
        text = decoder.decode(chunk)
        if text:
            collected.append(text)
            if on_output is not None:
                on_output(text)
    tail = decoder.decode(b"", final=True)
    if tail:
        collected.append(tail)
    await process.wait()


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
