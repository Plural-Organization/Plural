import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from plural.daemon.port import PortState, port_state, start_daemon


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def serve(body: bytes) -> HTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_a_free_port_is_free() -> None:
    assert port_state(free_port()) is PortState.FREE


def test_a_daemon_on_the_port_is_recognised() -> None:
    server = serve(json.dumps({"daemon": True, "version": "1"}).encode())
    try:
        assert port_state(server.server_port) is PortState.DAEMON
    finally:
        server.shutdown()


def test_something_else_on_the_port_is_busy() -> None:
    server = serve(b"<html>not plural</html>")
    try:
        assert port_state(server.server_port) is PortState.BUSY
    finally:
        server.shutdown()


def test_start_daemon_runs_it_and_waits_until_it_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = serve(json.dumps({"daemon": True}).encode())
    ran: list[list[str]] = []
    states = iter([PortState.FREE, PortState.DAEMON])

    def fake_state(_port: int) -> PortState:
        return next(states)

    class Fake:
        def __init__(self, command: list[str], **_: object) -> None:
            ran.append(command)

    monkeypatch.setattr("plural.daemon.port.port_state", fake_state)
    monkeypatch.setattr("plural.daemon.port.subprocess.Popen", Fake)
    try:
        assert (
            start_daemon(server.server_port, tmp_path / "logs" / "daemon.log") is PortState.DAEMON
        )
    finally:
        server.shutdown()
    assert ran[0][-3:-1] == ["daemon", "--port"]


def test_start_daemon_leaves_a_running_one_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def running(_port: int) -> PortState:
        return PortState.DAEMON

    def never(*_: object, **__: object) -> None:
        raise AssertionError("started a second daemon")

    monkeypatch.setattr("plural.daemon.port.port_state", running)
    monkeypatch.setattr("plural.daemon.port.subprocess.Popen", never)
    assert start_daemon(1, tmp_path / "daemon.log") is PortState.DAEMON
