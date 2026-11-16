"""More than one copy of plural, and a daemon that outlived an update."""

import json
import os
import threading
from collections.abc import Generator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from plural import __version__
from plural.cli import account
from plural.cli.copies import copies_of
from plural.cli.main import app
from plural.daemon import port as daemon_port
from plural.daemon.port import PortState, daemon_version


def program(folder: Path, name: str = "plural") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return path


def test_copies_come_in_path_order_and_a_linked_copy_counts_once(tmp_path: Path) -> None:
    first = program(tmp_path / "usr" / "bin")
    mine = program(tmp_path / "home" / "bin")
    (tmp_path / "again").mkdir()
    (tmp_path / "again" / "plural").symlink_to(mine)
    path = os.pathsep.join(
        [str(tmp_path / "usr" / "bin"), str(tmp_path / "home" / "bin"), str(tmp_path / "again"), ""]
    )
    assert copies_of("plural", path) == [first.resolve(), mine.resolve()]


def test_a_missing_or_unrunnable_file_is_not_a_copy(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    (tmp_path / "text").mkdir()
    (tmp_path / "text" / "plural").write_text("not executable")
    (tmp_path / "dir" / "plural").mkdir(parents=True)
    path = os.pathsep.join(str(tmp_path / name) for name in ("empty", "text", "dir", "nowhere"))
    assert copies_of("plural", path) == []


def test_doctor_names_an_extra_copy_without_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    program(tmp_path / "a")
    program(tmp_path / "b")
    monkeypatch.setenv("PATH", f"{tmp_path / 'a'}{os.pathsep}{tmp_path / 'b'}")
    monkeypatch.setenv("PLURAL_DATA_DIR", str(tmp_path / "data"))
    result = CliRunner().invoke(app, ["doctor", "--workspace", str(tmp_path)])
    assert "copies of plural" in result.stdout
    assert "the first one runs" in result.stdout
    assert "copies of plural-host" not in result.stdout


@contextmanager
def status(body: object) -> Generator[int]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return None

        def do_GET(self) -> None:
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()


def test_a_daemon_says_its_version() -> None:
    with status({"daemon": True, "version": "0.2.20", "linked": True}) as port:
        assert daemon_version(port) == "0.2.20"
    with status({"daemon": True}) as port:
        assert daemon_version(port) is None
    with status(["not", "an", "object"]) as port:
        assert daemon_version(port) is None


def test_nothing_listening_has_no_version() -> None:
    assert daemon_version(1) is None


def _login_ends(monkeypatch: pytest.MonkeyPatch, running: str | None) -> None:
    def started(_port: int, _log: Path) -> PortState:
        return PortState.DAEMON

    def version(_port: int) -> str | None:
        return running

    monkeypatch.setattr(daemon_port, "start_daemon", started)
    monkeypatch.setattr(daemon_port, "daemon_version", version)


def test_login_says_when_the_daemon_that_answers_is_older(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _login_ends(monkeypatch, "0.0.1")
    account._start_daemon(47831)  # pyright: ignore[reportPrivateUsage]
    out = capsys.readouterr().out
    assert "daemon is running" in out
    assert "0.0.1" in out
    assert "plural stop" in out


@pytest.mark.parametrize("running", [__version__, None])
def test_login_stays_quiet_when_the_daemon_is_current_or_does_not_say(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], running: str | None
) -> None:
    _login_ends(monkeypatch, running)
    account._start_daemon(47831)  # pyright: ignore[reportPrivateUsage]
    assert "plural stop" not in capsys.readouterr().out
