import asyncio
import json
import sys
from pathlib import Path

import pytest

from plural.agent.mcp import (
    BROWSER_SERVER,
    McpError,
    McpHub,
    ServerSpec,
    browser_spec,
    disabled_builtins,
    importable,
    read_config,
    tool_name,
)
from plural.agent.tools.base import ToolError
from plural.protocol.models import McpStatus, SkillScope, ToolRisk

ECHO = str(Path(__file__).parents[1] / "fixtures" / "echo_mcp.py")


def echo_spec() -> ServerSpec:
    return ServerSpec(command=sys.executable, args=[ECHO])


async def settled(hub: McpHub, name: str) -> McpStatus:
    for _ in range(300):
        view = next(view for view in hub.views() if view.name == name)
        if view.status is not McpStatus.CONNECTING:
            return view.status
        await asyncio.sleep(0.05)
    raise AssertionError(f"{name} never finished connecting")


def hub_at(tmp_path: Path) -> McpHub:
    return McpHub(workspace=tmp_path / "ws", home=tmp_path / "home", logs=tmp_path / "logs")


def test_config_reads_the_claude_code_format(tmp_path: Path) -> None:
    path = tmp_path / ".mcp.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "plane": {"command": "npx", "args": ["-y", "plane-mcp"], "env": {"TOKEN": "x"}},
                    "linear": {"type": "http", "url": "https://mcp.linear.app/mcp"},
                    "bad name!": {"command": "x"},
                    "empty": {},
                }
            }
        )
    )
    servers = read_config(path)
    assert set(servers) == {"plane", "linear"}
    assert servers["plane"].transport == "stdio"
    assert servers["linear"].transport == "http"


def test_import_finds_claude_code_and_cursor_servers(tmp_path: Path) -> None:
    home, workspace = tmp_path / "home", tmp_path / "ws"
    home.mkdir()
    (home / ".claude.json").write_text(
        json.dumps(
            {
                "mcpServers": {"plane": {"command": "plane-mcp"}},
                "projects": {str(workspace): {"mcpServers": {"db": {"command": "pg-mcp"}}}},
            }
        )
    )
    (home / ".cursor").mkdir()
    (home / ".cursor" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"web": {"url": "https://w/mcp"}}})
    )
    assert set(importable(home, workspace)) == {"plane", "db", "web"}


def test_the_browser_launches_its_own_chrome_or_attaches_over_cdp(tmp_path: Path) -> None:
    launched = browser_spec("launch", tmp_path)
    assert launched.command == "npx"
    assert "@playwright/mcp@0.0.83" in launched.args
    assert launched.args[launched.args.index("--browser") + 1] == "chrome"
    assert launched.args[launched.args.index("--user-data-dir") + 1] == str(tmp_path / "profile")
    assert "--cdp-endpoint" not in launched.args

    attached = browser_spec("chrome", tmp_path)
    assert attached.args[attached.args.index("--cdp-endpoint") + 1] == "chrome"
    assert "--user-data-dir" not in attached.args
    assert attached.args[attached.args.index("--output-dir") + 1] == str(tmp_path / "output")
    assert attached.env == {}


async def test_a_builtin_server_starts_and_a_configured_one_replaces_it(tmp_path: Path) -> None:
    builtin = {BROWSER_SERVER: echo_spec(), "other": echo_spec()}
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"other": {"command": "x", "disabled": True}}})
    )
    hub = McpHub(
        workspace=workspace, home=tmp_path / "home", logs=tmp_path / "logs", builtin=builtin
    )
    hub.start()
    try:
        assert await settled(hub, BROWSER_SERVER) is McpStatus.READY
        views = {view.name: view for view in hub.views()}
        assert views[BROWSER_SERVER].scope is SkillScope.GLOBAL
        assert views["other"].status is McpStatus.OFF
        assert f"mcp__{BROWSER_SERVER}__echo" in {tool.name for tool in hub.tools()}
        assert read_config(workspace / ".mcp.json").keys() == {"other"}

        with pytest.raises(McpError, match="built in"):
            await hub.remove(BROWSER_SERVER)
        await hub.toggle(BROWSER_SERVER, enabled=False)
        settings = tmp_path / "home" / ".plural" / "mcp.json"
        assert disabled_builtins(settings) == {BROWSER_SERVER}
        assert read_config(settings) == {}
    finally:
        await hub.close()

    restarted = McpHub(
        workspace=workspace, home=tmp_path / "home", logs=tmp_path / "logs", builtin=builtin
    )
    restarted.start()
    try:
        views = {view.name: view for view in restarted.views()}
        assert views[BROWSER_SERVER].status is McpStatus.OFF
        await restarted.toggle(BROWSER_SERVER, enabled=True)
        assert disabled_builtins(settings) == frozenset()
        assert read_config(settings) == {}
    finally:
        await restarted.close()


def test_long_tool_names_are_shortened_but_stay_unique() -> None:
    assert tool_name("plane", "list issues") == "mcp__plane__list_issues"
    long_a, long_b = tool_name("srv", "x" * 80 + "a"), tool_name("srv", "x" * 80 + "b")
    assert len(long_a) <= 64
    assert long_a != long_b


async def test_a_stdio_server_connects_and_its_tools_run(tmp_path: Path) -> None:
    hub = hub_at(tmp_path)
    hub.start()
    try:
        hub.add("echo", echo_spec(), SkillScope.PROJECT)
        assert await settled(hub, "echo") is McpStatus.READY
        tools = {tool.name: tool for tool in hub.tools()}
        assert set(tools) == {"mcp__echo__echo", "mcp__echo__add"}
        assert "text" in json.dumps(tools["mcp__echo__echo"].schema().parameters)

        prepared = tools["mcp__echo__echo"].prepare({"text": "hi"})
        assert (prepared.subject, prepared.risk) == ("echo/echo", ToolRisk.EXEC)
        result = await prepared.execute(None)  # pyright: ignore[reportArgumentType]
        assert result.content == "echo: hi"
        assert "echo" in read_config(tmp_path / "ws" / ".mcp.json")

        await hub.toggle("echo", enabled=False)
        assert hub.views()[0].status is McpStatus.OFF
        assert list(hub.tools()) == []
        with pytest.raises(ToolError, match="not connected"):
            await prepared.execute(None)  # pyright: ignore[reportArgumentType]
        assert read_config(tmp_path / "ws" / ".mcp.json")["echo"].disabled

        await hub.toggle("echo", enabled=True)
        assert await settled(hub, "echo") is McpStatus.READY
        await hub.remove("echo")
        assert hub.views() == ()
        assert read_config(tmp_path / "ws" / ".mcp.json") == {}
    finally:
        await hub.close()


async def test_a_server_that_cannot_start_reports_why(tmp_path: Path) -> None:
    hub = hub_at(tmp_path)
    hub.start()
    try:
        hub.add("ghost", ServerSpec(command="definitely-not-a-real-mcp-binary"), SkillScope.GLOBAL)
        assert await settled(hub, "ghost") is McpStatus.FAILED
        view = hub.views()[0]
        assert view.error
        assert view.scope is SkillScope.GLOBAL
        assert (tmp_path / "home" / ".plural" / "mcp.json").exists()
    finally:
        await hub.close()


async def test_secrets_in_the_config_are_known_for_redaction(tmp_path: Path) -> None:
    hub = hub_at(tmp_path)
    hub.add(
        "remote",
        ServerSpec(
            url="http://127.0.0.1:9/mcp", headers={"Authorization": "Bearer sk-very-secret"}
        ),
        SkillScope.PROJECT,
    )
    try:
        assert "Bearer sk-very-secret" in hub.secrets()
    finally:
        await hub.close()
