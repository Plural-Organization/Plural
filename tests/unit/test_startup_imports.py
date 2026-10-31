import subprocess
import sys

HEAVY = ("mcp",)


def test_the_host_modules_do_not_load_the_mcp_sdk_until_a_server_starts() -> None:
    code = (
        "import sys\n"
        "import plural.cli.main, plural.host.bootstrap, plural.agent.mcp\n"
        f"print([name for name in {HEAVY!r} if name in sys.modules])"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=60
    )
    assert result.stdout.strip() == "[]"
