import asyncio
import shutil
from dataclasses import dataclass
from typing import Final, Literal

Tool = Literal["claude", "codex"]

INSTALL_TIMEOUT_S: Final = 300.0
OUTPUT_TAIL_LINES: Final = 6


class ToolInstallError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ToolSpec:
    id: Tool
    label: str
    binary: str
    package: str
    login: str


SPECS: Final[tuple[ToolSpec, ...]] = (
    ToolSpec(
        "claude", "Claude Code CLI", "claude", "@anthropic-ai/claude-code", "claude auth login"
    ),
    ToolSpec("codex", "Codex CLI", "codex", "@openai/codex", "codex login"),
)
ADAPTER_TOOL: Final[dict[str, Tool]] = {"claude_code": "claude", "codex_cli": "codex"}
_BY_ID: Final = {spec.id: spec for spec in SPECS}


def tool_for(adapter: str) -> Tool | None:
    return ADAPTER_TOOL.get(adapter)


def is_installed(tool: Tool) -> bool:
    return shutil.which(_BY_ID[tool].binary) is not None


def install_command(tool: Tool) -> list[str] | None:
    npm = shutil.which("npm")
    if npm is None:
        return None
    return [npm, "install", "-g", _BY_ID[tool].package]


def manual_command(tool: Tool) -> str:
    return f"npm install -g {_BY_ID[tool].package}"


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
    command = install_command(tool)
    if command is None:
        raise ToolInstallError(
            f"npm was not found. Install Node.js, then run: {manual_command(tool)}"
        )
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
