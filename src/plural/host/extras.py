"""The model SDKs that ship as optional extras of plural-agent, and how the host adds them.

`plural-agent[anthropic]` and `plural-agent[openai]` keep the default install small. The modules
that import an SDK load only when a provider needs it, so the host can install one while it runs.
"""

import asyncio
import importlib
import importlib.metadata
import importlib.util
import shutil
import sys
from typing import Final, Literal

Extra = Literal["anthropic", "openai"]

EXTRAS: Final[tuple[Extra, ...]] = ("anthropic", "openai")
LABELS: Final[dict[Extra, str]] = {
    "anthropic": "Anthropic SDK (Claude API and Claude OAuth)",
    "openai": "OpenAI SDK (OpenAI and OpenAI-compatible servers)",
}
# The packages that must import for the extra to work.
MODULES: Final[dict[Extra, tuple[str, ...]]] = {
    "anthropic": ("anthropic", "pydantic_ai"),
    "openai": ("openai", "pydantic_ai"),
}
ADAPTER_EXTRA: Final[dict[str, Extra]] = {
    "anthropic": "anthropic",
    "anthropic_oauth": "anthropic",
    "openai": "openai",
}
DISTRIBUTION: Final = "plural-agent"
INSTALL_TIMEOUT_S: Final = 600.0
OUTPUT_TAIL_LINES: Final = 6


class InstallError(Exception):
    pass


def extra_for(adapter: str) -> Extra | None:
    return ADAPTER_EXTRA.get(adapter)


def is_installed(extra: Extra) -> bool:
    return all(importlib.util.find_spec(module) is not None for module in MODULES[extra])


def hint(extra: Extra) -> str:
    return f"uv tool install --force '{DISTRIBUTION}[{extra}]'"


def requirements(extra: Extra) -> list[str]:
    """The pins the installed plural-agent declares for an extra, read from its own metadata."""
    marker = f'extra == "{extra}"'
    found: list[str] = []
    for line in importlib.metadata.requires(DISTRIBUTION) or []:
        spec, _, condition = line.partition(";")
        if marker in condition.replace("'", '"'):
            found.append(spec.strip())
    return found


def install_command(packages: list[str]) -> list[str]:
    uv = shutil.which("uv")
    if uv is not None:
        return [uv, "pip", "install", "--python", sys.executable, *packages]
    return [sys.executable, "-m", "pip", "install", *packages]


async def install(extra: Extra) -> None:
    """Install an extra into the environment the host runs in. Only the two known extras are
    accepted and the pins come from the package's own metadata, so nothing here is client text."""
    packages = requirements(extra)
    if not packages:
        raise InstallError(f"this build of plural-agent has no {extra} extra, run: {hint(extra)}")
    process = await asyncio.create_subprocess_exec(
        *install_command(packages),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), INSTALL_TIMEOUT_S)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise InstallError(f"the install took longer than {INSTALL_TIMEOUT_S:g}s") from None
    if process.returncode != 0:
        tail = "\n".join(output.decode(errors="replace").strip().splitlines()[-OUTPUT_TAIL_LINES:])
        raise InstallError(f"the install failed, run: {hint(extra)}\n{tail}")
    importlib.invalidate_caches()
    if not is_installed(extra):
        raise InstallError(f"the {extra} SDK still does not import, run: {hint(extra)}")
