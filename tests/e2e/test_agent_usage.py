from pathlib import Path

import pytest

from plural.agent.providers.base import LlmEvent, Stop, ToolCallReady, ToolCallRequest, UsageReport
from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.client.connection import CommandRejected
from plural.protocol.commands import AgentsCreate, AgentsRemove, PromptSubmit
from plural.protocol.envelope import ErrorCode
from plural.protocol.events import AgentsChanged, RunEnded, UsageRecorded
from plural.protocol.models import Usage
from tests.e2e.support import running_session


def delegate(task: str) -> tuple[LlmEvent, ...]:
    call = ToolCallRequest(id="d1", name="agent", args={"agent": "explore", "task": task})
    return (
        UsageReport(usage=Usage(input_tokens=300, output_tokens=20)),
        ToolCallReady(call=call),
        Stop(reason="tool_use"),
    )


async def test_everyone_sees_what_each_model_and_agent_spent(tmp_path: Path) -> None:
    provider = FakeProvider(
        [
            delegate("look around"),
            (
                UsageReport(usage=Usage(input_tokens=40, output_tokens=5)),
                *use_tool("ls", "l1", path="."),
            ),
            reply("notes.txt is here"),
            (UsageReport(usage=Usage(input_tokens=500, output_tokens=30)), *reply("done")),
        ]
    )
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        await owner.client.send(PromptSubmit(text="what is here?"))
        recorded = await guest.next(UsageRecorded)
        await guest.next(RunEnded)

        lines = {(line.role, line.agent): line for line in recorded.lines}
        assert lines[("main", "")].uses == 1
        assert lines[("main", "")].usage.input_tokens == 800
        assert lines[("main", "explore")].uses == 1
        assert lines[("main", "explore")].usage.input_tokens == 40
        assert guest.client.projection.state.usage == recorded.lines


async def test_the_host_creates_and_removes_agents_for_the_room(tmp_path: Path) -> None:
    async with running_session(tmp_path, relayed=False, provider=FakeProvider()) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        assert [agent.name for agent in guest.client.projection.state.agents] == ["explore"]

        create = AgentsCreate(
            name="reviewer",
            description="Reviews diffs.",
            prompt="Review it.",
            tools=("read", "grep", "bash"),
        )
        with pytest.raises(CommandRejected) as rejected:
            await guest.client.send(create)
        assert rejected.value.error.code is ErrorCode.FORBIDDEN

        await owner.client.send(create)
        changed = await guest.next(AgentsChanged)
        reviewer = changed.agents[-1]
        assert (reviewer.name, reviewer.tools, reviewer.read_only) == (
            "reviewer",
            ("read", "grep", "bash"),
            False,
        )
        assert (tmp_path / "ws" / ".agents" / "agents" / "reviewer.md").exists()

        await owner.client.send(AgentsRemove(name="reviewer"))
        assert [agent.name for agent in (await guest.next(AgentsChanged)).agents] == ["explore"]
