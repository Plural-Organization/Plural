import json
import subprocess
import sys
from pathlib import Path


def test_machine_mode_host_quits_when_its_parent_closes_stdin(tmp_path: Path) -> None:
    command = [
        str(Path(sys.executable).parent / "plural-host"),
        "host",
        "--json",
        "--workspace",
        str(tmp_path),
        "--port",
        "0",
    ]
    environment = {"PLURAL_DATA_DIR": str(tmp_path / "data"), "PATH": "/usr/bin:/bin"}
    child = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        text=True,
    )
    assert child.stdout is not None
    assert child.stdin is not None
    try:
        ready = json.loads(child.stdout.readline())
        assert ready["type"] == "ready"
        child.stdin.close()
        assert child.wait(timeout=20) == 0
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=10)
