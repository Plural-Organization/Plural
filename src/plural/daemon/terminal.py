import asyncio
import shutil
import sys
from typing import Protocol


class TerminalUnavailable(Exception):
    """This computer has no terminal window the daemon can open."""


class Terminal(Protocol):
    async def run(self, command: str) -> None:
        """Opens a terminal window that runs the command and stays open."""
        ...


# Linux terminals, and how each takes a command to run.
_LINUX = (
    ("x-terminal-emulator", ("-e",)),
    ("gnome-terminal", ("--",)),
    ("konsole", ("-e",)),
    ("xterm", ("-e",)),
)


class SystemTerminal:
    """Opens the person's own terminal for a sign-in that only a terminal can do.

    The command is never client text: the daemon picks it from a short list (`claude auth login`,
    `codex login`), so no quoting is needed and nothing a page sends reaches a shell.
    """

    async def run(self, command: str) -> None:
        if sys.platform == "darwin":
            arguments = [
                "osascript",
                "-e",
                f'tell application "Terminal" to do script "{command}"',
                "-e",
                'tell application "Terminal" to activate',
            ]
        elif sys.platform.startswith("win"):
            arguments = ["cmd", "/c", "start", "", "cmd", "/k", command]
        else:
            found = next(((name, flags) for name, flags in _LINUX if shutil.which(name)), None)
            if found is None:
                raise TerminalUnavailable("no terminal to open (install xterm or gnome-terminal)")
            arguments = [found[0], *found[1], "sh", "-c", f"{command}; exec $SHELL"]
        try:
            process = await asyncio.create_subprocess_exec(
                *arguments,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError as error:
            raise TerminalUnavailable(f"could not open a terminal: {error}") from error
        if sys.platform == "darwin" and await process.wait() != 0:
            raise TerminalUnavailable("the Terminal app did not open")
