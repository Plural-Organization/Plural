"""Questions put to the computer: is a CLI signed in, which local model servers are running."""

import asyncio
import json
import shutil
from dataclasses import dataclass
from typing import Final, cast
from urllib.error import URLError
from urllib.request import urlopen

from pydantic import BaseModel, ConfigDict, ValidationError

CLI_TIMEOUT_S: Final = 10.0
LOCAL_TIMEOUT_S: Final = 1.0
MAX_LOCAL_BYTES: Final = 1_000_000
MAX_MODELS: Final = 200


@dataclass(frozen=True, slots=True)
class LocalServer:
    name: str
    preset: str
    base_url: str
    models: tuple[str, ...]


# Fixed loopback addresses only: the layer never probes an address a client names.
_LOCAL: Final[tuple[tuple[str, str, str, str], ...]] = (
    ("Ollama", "ollama", "http://127.0.0.1:11434/v1", "http://127.0.0.1:11434/api/tags"),
    ("LM Studio", "custom", "http://127.0.0.1:1234/v1", "http://127.0.0.1:1234/v1/models"),
)


async def _run(binary: str, *args: str) -> tuple[int, str] | None:
    """The exit code and output of a CLI, or None if it is missing or does not answer."""
    path = shutil.which(binary)
    if path is None:
        return None
    try:
        process = await asyncio.create_subprocess_exec(
            path,
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(process.communicate(), CLI_TIMEOUT_S)
    except (OSError, TimeoutError):
        return None
    return process.returncode or 0, out.decode(errors="replace")


async def claude_signed_in() -> bool | None:
    """Whether Claude Code has a sign-in. Its token stays with the CLI. None: could not tell."""
    result = await _run("claude", "auth", "status")
    if result is None:
        return None
    try:
        status = json.loads(result[1])
    except ValueError:
        return result[0] == 0 or None
    if not isinstance(status, dict):
        return None
    return bool(cast(dict[str, object], status).get("loggedIn"))


async def codex_signed_in() -> bool | None:
    result = await _run("codex", "login", "status")
    return None if result is None else result[0] == 0


class _Entry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    id: str | None = None


class _Listing(BaseModel):
    """What Ollama (`models`) and OpenAI-compatible servers (`data`) answer with."""

    model_config = ConfigDict(extra="ignore")

    models: list[_Entry] = []
    data: list[_Entry] = []


def models_in(body: object) -> tuple[str, ...]:
    try:
        listing = _Listing.model_validate(body)
    except ValidationError:
        return ()
    names = (entry.name or entry.id for entry in (*listing.models, *listing.data))
    return tuple(name for name in names if name)[:MAX_MODELS]


def _fetch(url: str) -> object | None:
    try:
        with urlopen(url, timeout=LOCAL_TIMEOUT_S) as response:
            return json.loads(response.read(MAX_LOCAL_BYTES))
    except (OSError, URLError, ValueError):
        return None


async def local_servers() -> list[LocalServer]:
    bodies = await asyncio.gather(*(asyncio.to_thread(_fetch, entry[3]) for entry in _LOCAL))
    return [
        LocalServer(name, preset, base_url, models_in(body))
        for (name, preset, base_url, _), body in zip(_LOCAL, bodies, strict=True)
        if body is not None
    ]
