from pathlib import Path

from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.core.policy.engine import PLAN_MODE
from plural.protocol.commands import PermissionModeSet, PromptSubmit
from plural.protocol.events import ApprovalRequested, PermissionModeChanged, RunEnded, ToolEnded
from plural.protocol.models import PermissionMode
from tests.e2e.support import running_session


def touch_provider() -> FakeProvider:
    return FakeProvider([use_tool("bash", "c1", command="touch made.txt"), reply("done")])


async def test_auto_mode_runs_commands_without_asking_the_host(tmp_path: Path) -> None:
    async with running_session(tmp_path, relayed=False, provider=touch_provider()) as session:
        owner = await session.owner()
        await owner.client.send(PermissionModeSet(mode=PermissionMode.AUTO))
        assert (await owner.next(PermissionModeChanged)).mode is PermissionMode.AUTO

        await owner.client.send(PromptSubmit(text="make the file"))
        assert (await owner.next(ToolEnded)).ok
        await owner.next(RunEnded)
        assert not any(isinstance(e, ApprovalRequested) for e in owner.events)


async def test_plan_mode_refuses_changes_and_tells_the_agent_why(tmp_path: Path) -> None:
    provider = touch_provider()
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        await owner.client.send(PermissionModeSet(mode=PermissionMode.PLAN))
        await owner.next(PermissionModeChanged)

        await owner.client.send(PromptSubmit(text="make the file"))
        ended = await owner.next(ToolEnded)
        await owner.next(RunEnded)

        assert not ended.ok
        assert PLAN_MODE in ended.output
        assert not (tmp_path / "ws" / "made.txt").exists()
        assert "plan mode" in str(provider.requests[0].messages[-1])
        assert not any(isinstance(e, ApprovalRequested) for e in owner.events)
