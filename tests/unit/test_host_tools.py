import json
from pathlib import Path
from typing import cast

import pytest

from plural.host import tools
from plural.host.bootstrap import Host
from plural.host.config import HostSettings
from plural.host.control import Control
from plural.host.tools import Tool, ToolInstallError


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

    monkeypatch.setattr("plural.host.tools.asyncio.create_subprocess_exec", spawn)
    return commands


def on_path(*names: str) -> object:
    def which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in names else None

    return which


def test_each_cli_adapter_maps_to_its_tool() -> None:
    assert tools.tool_for("claude_code") == "claude"
    assert tools.tool_for("codex_cli") == "codex"
    assert tools.tool_for("anthropic") is None
    assert tools.tool_for("fake") is None


def test_the_inventory_says_what_is_installed_and_whether_it_can_be_installed_here(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("plural.host.tools.shutil.which", on_path("claude", "npm"))
    claude, codex = tools.inventory()
    assert (claude["id"], claude["installed"], claude["canInstall"]) == ("claude", True, True)
    assert (codex["id"], codex["installed"], codex["canInstall"]) == ("codex", False, True)
    assert codex["command"] == "npm install -g @openai/codex"
    assert codex["login"] == "codex login"
    monkeypatch.setattr("plural.host.tools.shutil.which", on_path())
    assert [entry["canInstall"] for entry in tools.inventory()] == [False, False]


async def test_a_successful_install_runs_npm_with_a_fixed_package_and_checks_the_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands = fake_process(monkeypatch, 0)
    monkeypatch.setattr("plural.host.tools.shutil.which", on_path("npm", "claude"))
    await tools.install("claude")
    assert commands == [("/usr/bin/npm", "install", "-g", "@anthropic-ai/claude-code")]


async def test_without_npm_the_error_says_what_to_install_and_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands = fake_process(monkeypatch, 0)
    monkeypatch.setattr("plural.host.tools.shutil.which", on_path())
    with pytest.raises(ToolInstallError, match=r"Install Node.js, then run: npm install -g"):
        await tools.install("codex")
    assert commands == []


async def test_a_failed_install_shows_the_end_of_the_output_and_the_manual_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_process(monkeypatch, 1, b"\n".join(f"line {n}".encode() for n in range(20)))
    monkeypatch.setattr("plural.host.tools.shutil.which", on_path("npm"))
    with pytest.raises(ToolInstallError, match=r"npm install -g @openai/codex") as raised:
        await tools.install("codex")
    assert "line 19" in str(raised.value)
    assert "line 0" not in str(raised.value)


async def test_an_install_that_is_not_on_the_path_afterwards_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_process(monkeypatch, 0)
    monkeypatch.setattr("plural.host.tools.shutil.which", on_path("npm"))
    with pytest.raises(ToolInstallError, match=r"codex is not on the PATH"):
        await tools.install("codex")


async def test_the_control_channel_installs_only_a_known_tool_and_lists_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    asked: list[Tool] = []

    async def install(tool: Tool) -> None:
        asked.append(tool)

    monkeypatch.setattr("plural.host.control.install_tool", install)
    replies: list[dict[str, object]] = []
    control = Control(cast("Host", None), HostSettings(workspace=tmp_path), replies.append)
    await control.handle(json.dumps({"id": "t1", "type": "install", "tool": "claude"}))
    await control.handle(json.dumps({"id": "t2", "type": "install", "tool": "rm -rf /"}))
    await control.handle(json.dumps({"id": "c1", "type": "catalog"}))
    assert asked == ["claude"]
    assert replies[0] == {"type": "result", "id": "t1", "ok": True}
    assert [reply["id"] for reply in replies] == ["t1", "c1"]
    catalog = replies[1]
    assert {entry["id"] for entry in cast("list[dict[str, object]]", catalog["tools"])} == {
        "claude",
        "codex",
    }
    presets = {entry["id"]: entry for entry in cast("list[dict[str, object]]", catalog["presets"])}
    assert presets["claude_code"]["tool"] == "claude"
    assert presets["codex_cli"]["tool"] == "codex"
    assert presets["openai"]["tool"] is None
