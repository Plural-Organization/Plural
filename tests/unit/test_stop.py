import os
import subprocess
import sys
import threading
import time

import pytest
from typer.testing import CliRunner

from plural.cli import stop as stop_module
from plural.cli.main import app
from plural.cli.stop import Proc, is_daemon, is_plural, select, terminate


def test_plural_programs_are_told_from_other_commands() -> None:
    assert is_plural("/home/a/.local/share/plural/plural-host/plural-host daemon --port 47831")
    assert is_plural("/venv/bin/python3 /venv/bin/plural-host relay --port 8787")
    assert is_plural("python -c from plural.cli.main import app; app() daemon --port 47831")
    assert is_plural("uv run plural-host host --json")
    assert is_plural("plural")
    assert not is_plural("/venv/bin/python3 .venv/bin/plural-accounts")
    assert not is_plural("vim plural-host")
    assert not is_plural("")


def test_only_the_daemon_is_a_daemon() -> None:
    assert is_daemon("plural-host daemon --port 47831")
    assert not is_daemon("plural-host host --json --workspace /w")


PROCS = [
    Proc(1, 0, "/sbin/launchd"),
    Proc(100, 1, "plural-host daemon --port 47831"),
    Proc(101, 100, "plural-host host --json --workspace /w"),
    Proc(102, 101, "npm exec @playwright/mcp"),
    Proc(103, 102, "node playwright-mcp"),
    Proc(200, 1, "plural-host relay --port 8787"),
    Proc(300, 1, "/venv/bin/python3 .venv/bin/plural-accounts"),
    Proc(400, 1, "zsh"),
    Proc(401, 400, "plural"),
    Proc(402, 401, "plural-host host --json"),
    Proc(403, 402, "claude"),
]


def pids(found: list[Proc]) -> set[int]:
    return {item.pid for item in found}


def test_everything_of_plural_goes_with_what_it_started() -> None:
    found = select(PROCS, daemon_only=False, me=999)
    assert pids(found) == {100, 101, 102, 103, 200, 401, 402, 403}


def test_the_daemon_scope_leaves_relays_and_terminals_alone() -> None:
    found = select(PROCS, daemon_only=True, me=999)
    assert pids(found) == {100, 101, 102, 103}


def test_the_command_and_what_it_runs_under_are_never_chosen() -> None:
    procs = [*PROCS, Proc(500, 401, "/bin/sh -c plural stop"), Proc(501, 500, "plural stop")]
    found = select(procs, daemon_only=False, me=501)
    assert not pids(found) & {401, 500, 501}
    assert 402 in pids(found)


def spawn(code: str) -> subprocess.Popen[bytes]:
    child = subprocess.Popen([sys.executable, "-c", code], start_new_session=True)
    threading.Thread(target=child.wait, daemon=True).start()
    time.sleep(0.4)
    return child


def test_a_process_that_will_not_end_is_killed_after_the_grace() -> None:
    polite = spawn("import time; time.sleep(60)")
    stubborn = spawn(
        "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
    )
    ended, killed = terminate([polite.pid, stubborn.pid], grace_s=1.0, alive=_alive)
    assert ended == [polite.pid]
    assert killed == [stubborn.pid]
    time.sleep(0.3)
    assert not _alive(polite.pid)
    assert not _alive(stubborn.pid)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_the_command_lists_and_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    stopped: list[list[int]] = []

    def record(found: list[int]) -> tuple[list[int], list[int]]:
        stopped.append(found)
        return [], []

    monkeypatch.setattr(stop_module, "snapshot", lambda: PROCS)
    monkeypatch.setattr(stop_module, "terminate", record)
    result = CliRunner().invoke(app, ["stop", "--dry-run"])
    assert result.exit_code == 0
    assert "8 would stop" in result.output
    assert stopped == []
    CliRunner().invoke(app, ["stop", "--daemon"])
    assert sorted(stopped[0]) == [100, 101, 102, 103]


def test_nothing_running_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stop_module, "snapshot", lambda: [Proc(1, 0, "launchd")])
    result = CliRunner().invoke(app, ["stop"])
    assert result.exit_code == 0
    assert "Nothing of Plural is running" in result.output
