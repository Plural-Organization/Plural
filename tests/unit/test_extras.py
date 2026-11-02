import json
from pathlib import Path
from typing import cast

import pytest

from plural.host import extras
from plural.host.bootstrap import Host
from plural.host.config import HostSettings
from plural.host.control import Control
from plural.host.extras import Extra, InstallError


def present(_: Extra) -> bool:
    return True


def absent(_: Extra) -> bool:
    return False


def uv_path(_: str) -> str | None:
    return "/bin/uv"


def no_uv(_: str) -> str | None:
    return None


class FakeProcess:
    def __init__(self, code: int, output: bytes) -> None:
        self.returncode = code
        self._output = output

    async def communicate(self) -> tuple[bytes, None]:
        return self._output, None


def fake_process(
    monkeypatch: pytest.MonkeyPatch, code: int, output: bytes = b""
) -> list[tuple[str, ...]]:
    commands: list[tuple[str, ...]] = []

    async def spawn(*command: str, **_: object) -> FakeProcess:
        commands.append(command)
        return FakeProcess(code, output)

    monkeypatch.setattr("plural.host.extras.asyncio.create_subprocess_exec", spawn)
    return commands


def test_each_extra_names_its_own_sdk_and_nothing_else() -> None:
    anthropic = extras.requirements("anthropic")
    openai = extras.requirements("openai")
    assert any(pin.startswith("anthropic") for pin in anthropic)
    assert any(pin.startswith("openai") for pin in openai)
    assert not any(pin.startswith("openai") for pin in anthropic)
    assert not any(pin.startswith("anthropic") for pin in openai)


def test_the_adapters_map_to_the_sdk_they_import() -> None:
    assert extras.extra_for("anthropic") == extras.extra_for("anthropic_oauth") == "anthropic"
    assert extras.extra_for("openai") == "openai"
    assert extras.extra_for("claude_code") is None
    assert extras.extra_for("codex_cli") is None
    assert extras.extra_for("fake") is None


def test_uv_installs_into_the_hosts_own_environment_and_pip_is_the_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("plural.host.extras.shutil.which", uv_path)
    assert extras.install_command(["a"])[:4] == ["/bin/uv", "pip", "install", "--python"]
    monkeypatch.setattr("plural.host.extras.shutil.which", no_uv)
    assert extras.install_command(["a"])[1:] == ["-m", "pip", "install", "a"]


async def test_a_successful_install_checks_that_the_sdk_imports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands = fake_process(monkeypatch, 0)
    monkeypatch.setattr("plural.host.extras.is_installed", present)
    await extras.install("openai")
    [command] = commands
    assert any(part.startswith("openai") for part in command)


async def test_an_install_that_leaves_the_sdk_missing_is_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_process(monkeypatch, 0)
    monkeypatch.setattr("plural.host.extras.is_installed", absent)
    with pytest.raises(InstallError, match=r"plural-agent\[anthropic\]"):
        await extras.install("anthropic")


async def test_a_failed_install_shows_the_end_of_the_output_and_the_manual_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_process(monkeypatch, 1, b"\n".join(f"line {n}".encode() for n in range(20)))
    with pytest.raises(InstallError, match=r"plural-agent\[openai\]") as raised:
        await extras.install("openai")
    assert "line 19" in str(raised.value)
    assert "line 0" not in str(raised.value)


async def test_the_control_channel_installs_only_a_known_extra(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    asked: list[Extra] = []

    async def install(extra: Extra) -> None:
        asked.append(extra)

    monkeypatch.setattr("plural.host.control.install", install)
    replies: list[dict[str, object]] = []
    control = Control(cast("Host", None), HostSettings(workspace=tmp_path), replies.append)
    await control.handle(json.dumps({"id": "i1", "type": "install", "extra": "anthropic"}))
    await control.handle(json.dumps({"id": "i2", "type": "install", "extra": "rm -rf /"}))
    await control.handle(json.dumps({"id": "i3", "type": "install"}))
    assert asked == ["anthropic"]
    assert replies[0] == {"type": "result", "id": "i1", "ok": True}
    # An unknown extra never reaches the installer, and a missing one is named.
    assert [reply["id"] for reply in replies] == ["i1", "i3"]
    assert replies[1]["ok"] is False


async def test_a_failed_install_is_reported_to_the_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def install(extra: Extra) -> None:
        raise InstallError("no network")

    monkeypatch.setattr("plural.host.control.install", install)
    replies: list[dict[str, object]] = []
    control = Control(cast("Host", None), HostSettings(workspace=tmp_path), replies.append)
    await control.handle(json.dumps({"id": "i1", "type": "install", "extra": "openai"}))
    assert replies == [{"type": "result", "id": "i1", "ok": False, "error": "no network"}]
