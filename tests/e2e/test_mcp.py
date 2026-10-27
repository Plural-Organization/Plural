import asyncio
import sys
from pathlib import Path

import pytest
from pydantic import JsonValue

from plural.agent.providers.base import Stop, ToolCallReady, ToolCallRequest
from plural.agent.providers.fake import FakeProvider, reply
from plural.client.connection import CommandRejected
from plural.protocol.commands import ApprovalRespond, McpAdd, McpToggle, PromptSubmit
from plural.protocol.envelope import ErrorCode
from plural.protocol.events import ApprovalRequested, McpChanged, RunEnded, ToolEnded
from plural.protocol.models import ApprovalDecision, McpStatus
from tests.e2e.support import Watcher, running_session

ECHO = str(Path(__file__).parents[1] / "fixtures" / "echo_mcp.py")


def call(name: str, **args: JsonValue) -> tuple[ToolCallReady, Stop]:
    return ToolCallReady(call=ToolCallRequest(id="c1", name=name, args=args)), Stop(
        reason="tool_use"
    )


async def ready(watcher: Watcher, name: str) -> None:
    for _ in range(200):
        servers = {server.name: server for server in watcher.client.projection.state.mcp}
        if name in servers and servers[name].status is not McpStatus.CONNECTING:
            assert servers[name].status is McpStatus.READY, servers[name].error
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"{name} never connected")


async def test_the_host_connects_a_server_and_its_tools_ask_first(tmp_path: Path) -> None:
    provider = FakeProvider([call("mcp__echo__echo", text="hello"), reply("done")])
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")

        with pytest.raises(CommandRejected) as rejected:
            await guest.client.send(McpAdd(name="echo", command=sys.executable, args=(ECHO,)))
        assert rejected.value.error.code is ErrorCode.FORBIDDEN

        await owner.client.send(McpAdd(name="echo", command=sys.executable, args=(ECHO,)))
        await guest.next(McpChanged)
        await ready(guest, "echo")
        assert guest.client.projection.state.mcp[0].tools == 2

        await owner.client.send(PromptSubmit(text="say hello through mcp"))
        approval = (await owner.next(ApprovalRequested)).approval
        assert approval.call.name == "mcp__echo__echo"
        assert approval.call.subject == "echo/echo"
        await owner.client.send(
            ApprovalRespond(approval_id=approval.id, decision=ApprovalDecision.ONCE)
        )
        ended = await owner.next(ToolEnded)
        assert ended.ok
        assert ended.output == "echo: hello"
        await owner.next(RunEnded)
        assert any(tool.name == "mcp__echo__echo" for tool in provider.requests[0].tools)

        await owner.client.send(McpToggle(name="echo", enabled=False))
        for _ in range(100):
            if guest.client.projection.state.mcp[0].status is McpStatus.OFF:
                break
            await asyncio.sleep(0.05)
        assert guest.client.projection.state.mcp[0].status is McpStatus.OFF


async def test_secrets_given_with_a_server_stay_out_of_the_room(tmp_path: Path) -> None:
    async with running_session(tmp_path, relayed=False, provider=FakeProvider()) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        await owner.client.send(
            McpAdd(
                name="echo",
                command=sys.executable,
                args=(ECHO,),
                env={"ECHO_TOKEN": "tok-very-secret-123"},
            )
        )
        await ready(guest, "echo")
        assert "tok-very-secret-123" not in guest.client.projection.state.model_dump_json()
        assert "tok-very-secret-123" in (tmp_path / "ws" / ".mcp.json").read_text()
