import os
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape

console = Console()

NAMES = frozenset({"plural", "plural-host"})
GRACE_S = 5.0


@dataclass(frozen=True, slots=True)
class Proc:
    pid: int
    ppid: int
    command: str


def _base(token: str) -> str:
    return token.rsplit("/", 1)[-1]


def is_plural(command: str) -> bool:
    """Whether a command line is one of Plural's programs: `plural`, `plural-host`, and the daemon
    started from source. Other services (the accounts server) are not."""
    tokens = command.split()
    if not tokens:
        return False
    head = _base(tokens[0])
    if head in NAMES:
        return True
    if head.startswith("python") and len(tokens) > 1:
        return _base(tokens[1]) in NAMES or "plural.cli.main" in command
    return head == "uv" and tokens[1:2] == ["run"] and len(tokens) > 2 and _base(tokens[2]) in NAMES


def is_daemon(command: str) -> bool:
    return is_plural(command) and " daemon" in command


def snapshot() -> list[Proc]:
    """Every process of this computer, from `ps`."""
    out = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,command="], capture_output=True, text=True, check=True
    ).stdout
    found: list[Proc] = []
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            found.append(Proc(int(parts[0]), int(parts[1]), parts[2]))
    return found


def select(procs: list[Proc], *, daemon_only: bool, me: int) -> list[Proc]:
    """What to stop: the roots (every Plural process, or just the daemons) and all they started,
    the agents and their tools included. Never this command or what it runs under."""
    by_pid = {item.pid: item for item in procs}
    protected = {me}
    cursor = by_pid.get(me)
    while cursor is not None and cursor.ppid not in protected and cursor.ppid > 1:
        protected.add(cursor.ppid)
        cursor = by_pid.get(cursor.ppid)
    match = is_daemon if daemon_only else is_plural
    chosen = {item.pid for item in procs if match(item.command)} - protected
    grew = True
    while grew:
        grew = False
        for item in procs:
            if item.ppid in chosen and item.pid not in chosen and item.pid not in protected:
                chosen.add(item.pid)
                grew = True
    return [item for item in procs if item.pid in chosen]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminate(
    pids: list[int],
    *,
    grace_s: float = GRACE_S,
    alive: Callable[[int], bool] = _alive,
) -> tuple[list[int], list[int]]:
    """Ask them to end, then kill those that do not within `grace_s`. Returns (ended, killed)."""
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            continue
    deadline = time.monotonic() + grace_s
    left = [pid for pid in pids if alive(pid)]
    while left and time.monotonic() < deadline:
        time.sleep(0.1)
        left = [pid for pid in left if alive(pid)]
    killed: list[int] = []
    for pid in left:
        try:
            os.kill(pid, signal.SIGKILL)
            killed.append(pid)
        except OSError:
            continue
    return [pid for pid in pids if pid not in killed], killed


def stop_daemon() -> int:
    """Ends the daemon and the rooms it started, quietly. How many processes went."""
    try:
        found = select(snapshot(), daemon_only=True, me=os.getpid())
    except (OSError, subprocess.CalledProcessError):
        return 0
    terminate([item.pid for item in found])
    return len(found)


def stop(
    daemon_only: Annotated[
        bool, typer.Option("--daemon", help="Only the daemon and the rooms it started.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show what would stop, stop nothing.")
    ] = False,
) -> None:
    """Stop every Plural process on this computer: the daemon, rooms, relays, agents and tools."""
    try:
        found = select(snapshot(), daemon_only=daemon_only, me=os.getpid())
    except (OSError, subprocess.CalledProcessError) as error:
        console.print(f"[red]Could not list processes: {escape(str(error))}[/red]")
        raise typer.Exit(1) from error
    if not found:
        console.print("Nothing of Plural is running.")
        return
    for item in found:
        console.print(f"  [dim]{item.pid}[/dim]  {escape(item.command[:110])}", soft_wrap=True)
    if dry_run:
        console.print(f"{len(found)} would stop.")
        return
    ended, killed = terminate([item.pid for item in found])
    console.print(
        f"Stopped {len(ended) + len(killed)}"
        + (f", {len(killed)} of them did not answer and were killed." if killed else ".")
    )
