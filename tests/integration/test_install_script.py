import hashlib
import http.server
import io
import os
import platform
import signal
import subprocess
import tarfile
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

INSTALLER = Path(__file__).resolve().parents[2] / "install.sh"
VERSION = "9.9.9"
SLOW_SIZE = 200 * 1024 * 1024

pytestmark = pytest.mark.skipif(os.name != "posix", reason="the installer is a POSIX script")


def _os_arch() -> tuple[str, str]:
    system = "darwin" if platform.system() == "Darwin" else "linux"
    arch = "arm64" if platform.machine().lower() in {"arm64", "aarch64"} else "x64"
    return system, arch


def _archive(files: dict[str, tuple[bytes, int]]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, (content, mode) in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = mode
            archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def release_assets() -> dict[str, bytes]:
    """A release as the installer expects it: gzip archives with their checksums."""
    system, arch = _os_arch()
    script = f"#!/bin/sh\necho {VERSION}\n".encode()
    archives = {
        f"plural-{system}-{arch}.tar.gz": _archive({"plural": (script, 0o755)}),
        f"plural-host-{system}-{arch}.tar.gz": _archive(
            {"plural-host/plural-host": (script, 0o755)}
        ),
    }
    assets = dict(archives)
    for name, data in archives.items():
        assets[f"{name}.sha256"] = f"{hashlib.sha256(data).hexdigest()}  {name}\n".encode()
    return assets


@contextmanager
def release_server(slow: bool) -> Generator[int]:
    """Serves the release. With slow, the archives never finish, so a run stays in its download."""
    assets = release_assets()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return None

        def _asset(self) -> tuple[str, bytes] | None:
            name = self.path.rsplit("/", 1)[-1]
            data = assets.get(name)
            if data is None:
                self.send_error(404)
                return None
            return name, data

        def do_HEAD(self) -> None:
            found = self._asset()
            if found is None:
                return
            name, data = found
            self.send_response(200)
            self.send_header(
                "Content-Length", str(SLOW_SIZE if slow and name.endswith(".gz") else len(data))
            )
            self.end_headers()

        def do_GET(self) -> None:
            found = self._asset()
            if found is None:
                return
            name, data = found
            if not (slow and name.endswith(".gz")):
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(SLOW_SIZE))
            self.end_headers()
            try:
                while True:
                    self.wfile.write(b"x" * 4096)
                    self.wfile.flush()
                    time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError):
                return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()


def environment(home: Path, port: int) -> dict[str, str]:
    bin_dir = home / "bin"
    return {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": str(home),
        "PLURAL_VERSION": VERSION,
        "PLURAL_RELEASE_URL": f"http://127.0.0.1:{port}/releases",
        "PLURAL_INSTALL_DIR": str(bin_dir),
    }


def start(home: Path, port: int) -> subprocess.Popen[str]:
    return subprocess.Popen(
        ["sh", str(INSTALLER)],
        env=environment(home, port),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )


def curls_of(port: int) -> list[str]:
    listing = subprocess.run(
        ["ps", "-axo", "pid=,command="], capture_output=True, text=True, check=True
    ).stdout
    return [line for line in listing.splitlines() if f"127.0.0.1:{port}" in line and "curl" in line]


def wait_for(condition: Callable[[], bool], what: str, seconds: float = 20) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {what}")


def ctrl_c(process: subprocess.Popen[str]) -> None:
    """What the terminal does: the signal goes to the whole foreground process group."""
    os.killpg(process.pid, signal.SIGINT)


def lock_of(home: Path) -> Path:
    return home / ".cache" / "plural" / "install.lock"


def test_a_release_installs(tmp_path: Path) -> None:
    with release_server(slow=False) as port:
        done = subprocess.run(
            ["sh", str(INSTALLER)],
            env=environment(tmp_path, port),
            capture_output=True,
            text=True,
            timeout=60,
        )
    assert done.returncode == 0, done.stderr
    assert f"plural {VERSION} is installed" in done.stdout
    assert (tmp_path / "bin" / "plural").exists()
    assert (tmp_path / "bin" / "plural-host").exists()
    assert not lock_of(tmp_path).exists()


def test_interrupting_leaves_no_download_running(tmp_path: Path) -> None:
    with release_server(slow=True) as port:
        process = start(tmp_path, port)
        wait_for(lambda: len(curls_of(port)) >= 2, "both downloads to start")
        ctrl_c(process)
        process.communicate(timeout=20)
        assert process.returncode == 130
        # A background curl ignores the terminal's Ctrl+C, so the installer has to stop it itself.
        wait_for(lambda: curls_of(port) == [], "the downloads to stop", seconds=10)
    assert not lock_of(tmp_path).exists()


def test_a_second_install_is_refused_while_one_runs(tmp_path: Path) -> None:
    with release_server(slow=True) as port:
        first = start(tmp_path, port)
        try:
            wait_for(
                lambda: lock_of(tmp_path).exists() and len(curls_of(port)) >= 2, "the first run"
            )
            second = subprocess.run(
                ["sh", str(INSTALLER)],
                env=environment(tmp_path, port),
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert second.returncode == 1
            assert "another plural install is running" in second.stderr
            assert first.poll() is None
        finally:
            ctrl_c(first)
            first.communicate(timeout=20)
        wait_for(lambda: curls_of(port) == [], "the downloads to stop", seconds=10)


def test_a_lock_left_by_a_dead_run_is_taken_over(tmp_path: Path) -> None:
    gone = subprocess.Popen(["true"])
    gone.wait()
    lock = lock_of(tmp_path)
    lock.mkdir(parents=True)
    (lock / "pid").write_text(f"{gone.pid}\n")
    with release_server(slow=False) as port:
        done = subprocess.run(
            ["sh", str(INSTALLER)],
            env=environment(tmp_path, port),
            capture_output=True,
            text=True,
            timeout=60,
        )
    assert done.returncode == 0, done.stderr
    assert not lock.exists()
