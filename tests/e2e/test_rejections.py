from pathlib import Path

from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.protocol.commands import ApprovalRespond, PromptSubmit
from plural.protocol.events import ApprovalRequested, Event, RunEnded, ToolEnded
from plural.protocol.models import ApprovalDecision
from tests.e2e.support import running_session


def tool_outputs(events: list[Event]) -> list[str]:
    return [e.output for e in events if isinstance(e, ToolEnded)]


def repeated_rm(blocked: str = "rm") -> FakeProvider:
    return FakeProvider(
        [
            use_tool("bash", "c1", command=f"{blocked} a.txt"),
            use_tool("bash", "c2", command=f"{blocked} -f a.txt"),
            use_tool("bash", "c3", command=f"{blocked} -v b.txt"),
            reply("I will ask you instead."),
        ]
    )


async def test_host_is_asked_only_until_the_limit(tmp_path: Path) -> None:
    async with running_session(tmp_path, relayed=False, provider=repeated_rm()) as session:
        owner = await session.owner()
        await owner.client.send(PromptSubmit(text="remove a.txt"))
        for _ in range(2):
            approval = (await owner.next(ApprovalRequested)).approval
            await owner.client.send(
                ApprovalRespond(approval_id=approval.id, decision=ApprovalDecision.REJECT)
            )
        ended = await owner.next(RunEnded)

        outputs = tool_outputs(owner.events)
        assert len(outputs) == 3
        assert all("ask the user" in output for output in outputs)
        assert "repeatedly" in outputs[2]
        assert ended.error is None
        assert len([e for e in owner.events if isinstance(e, ApprovalRequested)]) == 2


async def test_block_denies_the_rest_of_the_class(tmp_path: Path) -> None:
    async with running_session(tmp_path, relayed=False, provider=repeated_rm("curl")) as session:
        owner = await session.owner()
        await owner.client.send(PromptSubmit(text="fetch it"))
        approval = (await owner.next(ApprovalRequested)).approval
        await owner.client.send(
            ApprovalRespond(approval_id=approval.id, decision=ApprovalDecision.BLOCK)
        )
        await owner.next(RunEnded)

        outputs = tool_outputs(owner.events)
        assert "blocked by the host" in outputs[0]
        assert all("ask the user" in output for output in outputs[1:])
        assert len([e for e in owner.events if isinstance(e, ApprovalRequested)]) == 1
