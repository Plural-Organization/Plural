import asyncio
import shutil
from dataclasses import dataclass
from typing import Annotated, Final

from pydantic import AfterValidator

from plural.agent.providers.cli import CLI_PROVIDERS, CliProvider


def _known(tool: str) -> str:
    if tool not in _BY_ID:
        raise ValueError(f"unknown tool: {tool}")
    return tool


# A CLI the host can check for and install, named by its binary (claude, codex, gemini…). A
# client names it, so only a known one passes: install never runs a command a client chose.
Tool = Annotated[str, AfterValidator(_known)]

NPM_INSTALL: Final = "npm install -g "

INSTALL_TIMEOUT_S: Final = 300.0
OUTPUT_TAIL_LINES: Final = 6


class ToolInstallError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ToolSpec:
    id: Tool
    label: str
    binary: str
    # How to install it by hand; an npm package the host can also install itself.
    command: str
    package: str | None
    login: str


def _spec(provider: type[CliProvider]) -> ToolSpec:
    npm = provider.install.startswith(NPM_INSTALL)
    return ToolSpec(
        id=provider.binary,
        label=provider.label,
        binary=provider.binary,
        command=provider.install,
        package=provider.install.removeprefix(NPM_INSTALL) if npm else None,
        login=provider.login,
    )


SPECS: Final[tuple[ToolSpec, ...]] = tuple(_spec(cli) for cli in CLI_PROVIDERS.values())
ADAPTER_TOOL: Final[dict[str, str]] = {
    adapter: cli.binary for adapter, cli in CLI_PROVIDERS.items()
}
_BY_ID: Final = {spec.id: spec for spec in SPECS}


def tool_for(adapter: str) -> Tool | None:
    return ADAPTER_TOOL.get(adapter)


def is_installed(tool: Tool) -> bool:
    return shutil.which(_BY_ID[tool].binary) is not None


def install_command(tool: Tool) -> list[str] | None:
    package = _BY_ID[tool].package
    npm = shutil.which("npm")
    if package is None or npm is None:
        return None
    return [npm, "install", "-g", package]


def manual_command(tool: Tool) -> str:
    return _BY_ID[tool].command


def describe(spec: ToolSpec) -> dict[str, object]:
    return {
        "id": spec.id,
        "label": spec.label,
        "installed": is_installed(spec.id),
        "command": manual_command(spec.id),
        "canInstall": install_command(spec.id) is not None,
        "login": spec.login,
    }


def inventory() -> list[dict[str, object]]:
    return [describe(spec) for spec in SPECS]


async def install(tool: Tool) -> None:
    if tool not in _BY_ID:
        raise ToolInstallError(f"unknown tool: {tool}")
    command = install_command(tool)
    if command is None:
        needs = "npm was not found. Install Node.js, then run" if _BY_ID[tool].package else "Run"
        raise ToolInstallError(f"{needs}: {manual_command(tool)}")
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), INSTALL_TIMEOUT_S)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise ToolInstallError(
            f"the install took longer than {INSTALL_TIMEOUT_S:g}s, run it yourself: "
            f"{manual_command(tool)}"
        ) from None
    if process.returncode != 0:
        tail = "\n".join(output.decode(errors="replace").strip().splitlines()[-OUTPUT_TAIL_LINES:])
        raise ToolInstallError(
            f"the install failed, run it yourself in a terminal: {manual_command(tool)}\n{tail}"
        )
    if not is_installed(tool):
        raise ToolInstallError(
            f"installed, but {_BY_ID[tool].binary} is not on the PATH of the host. "
            "Open a new terminal, or add npm's global bin folder to PATH"
        )
