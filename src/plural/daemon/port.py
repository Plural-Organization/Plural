import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from enum import StrEnum
from pathlib import Path
from typing import cast


class PortState(StrEnum):
    FREE = "free"
    DAEMON = "daemon"
    BUSY = "busy"


def port_state(port: int) -> PortState:
    """Whether the loopback port is free, held by a Plural daemon already, or by something else."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        if probe.connect_ex(("127.0.0.1", port)) != 0:
            return PortState.FREE
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/status", timeout=1.5) as answer:
            body = json.loads(answer.read(4096))
    except (OSError, ValueError, urllib.error.URLError):
        return PortState.BUSY
    if isinstance(body, dict) and cast("dict[str, object]", body).get("daemon") is True:
        return PortState.DAEMON
    return PortState.BUSY


def daemon_command(port: int) -> list[str]:
    """The command that runs the daemon with the program that is running now."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "daemon", "--port", str(port)]
    return [
        sys.executable,
        "-c",
        "from plural.cli.main import app; app()",
        "daemon",
        "--port",
        str(port),
    ]


def start_daemon(port: int, log: Path, *, wait_s: float = 8.0) -> PortState:
    """Runs the daemon in the background unless one answers already; says what the port holds.

    The daemon outlives this process and writes to `log`. FREE after the wait: it did not come up.
    """
    state = port_state(port)
    if state is not PortState.FREE:
        return state
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as out:
        subprocess.Popen(
            daemon_command(port),
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=out,
            start_new_session=True,
        )
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        time.sleep(0.25)
        state = port_state(port)
        if state is not PortState.FREE:
            return state
    return PortState.FREE
