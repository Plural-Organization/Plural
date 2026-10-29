import asyncio
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class RepoFacts:
    name: str
    branch: str | None


async def _git(root: Path, *args: str) -> str | None:
    try:
        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(root),
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return None
    try:
        output, _ = await asyncio.wait_for(process.communicate(), 5)
    except TimeoutError:
        process.kill()
        await process.wait()
        return None
    text = output.decode(errors="replace").strip()
    return text if process.returncode == 0 and text else None


async def git_branch(root: Path) -> str | None:
    branch = await _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if branch is None:
        return None
    return "detached HEAD" if branch == "HEAD" else branch


def name_from_remote(remote: str) -> str | None:
    tail = urlsplit(remote).path if "://" in remote else remote.rsplit(":", 1)[-1]
    name = tail.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    return name or None


async def repo_facts(root: Path) -> RepoFacts:
    remote = await _git(root, "config", "--get", "remote.origin.url")
    name = name_from_remote(remote) if remote else None
    return RepoFacts(name=name or root.name or "project", branch=await git_branch(root))
