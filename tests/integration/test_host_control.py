import json
import subprocess
import sys
from pathlib import Path

SECRET = "gsk_Zq9vLw3pT7xN2mB8kR4yH6cD1fJ5sG0aE"


def test_a_client_configures_the_host_over_stdin_and_the_key_stays_off_disk(
    tmp_path: Path,
) -> None:
    data = tmp_path / "data"
    command = [
        str(Path(sys.executable).parent / "plural-host"),
        "host",
        "--json",
        "--workspace",
        str(tmp_path),
        "--port",
        "0",
    ]
    child = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={"PLURAL_DATA_DIR": str(data), "PATH": "/usr/bin:/bin"},
        text=True,
    )
    assert child.stdout is not None
    assert child.stdin is not None
    try:
        assert json.loads(child.stdout.readline())["type"] == "ready"

        message = {
            "id": "c1",
            "type": "configure",
            "config": {"provider": "fake", "api_key": SECRET},
        }
        child.stdin.write(json.dumps(message) + "\n")
        child.stdin.flush()
        reply = json.loads(child.stdout.readline())
        assert reply == {"type": "result", "id": "c1", "ok": True, "agent": "demo agent (scripted)"}

        child.stdin.write(
            json.dumps({"id": "c2", "type": "test", "config": {"provider": "fake"}}) + "\n"
        )
        child.stdin.flush()
        probed = json.loads(child.stdout.readline())
        assert probed["id"] == "c2"
        assert probed["ok"] is True

        child.stdin.close()
        assert child.wait(timeout=20) == 0
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=10)

    leaked = [
        path for path in data.rglob("*") if path.is_file() and SECRET.encode() in path.read_bytes()
    ]
    assert leaked == []
    assert SECRET not in (child.stderr.read() if child.stderr else "")
