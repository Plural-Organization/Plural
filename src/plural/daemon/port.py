import json
import socket
import urllib.error
import urllib.request
from enum import StrEnum
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
