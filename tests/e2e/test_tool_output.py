from pathlib import Path

from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.protocol.commands import ApprovalRespond, PromptSubmit
from plural.protocol.events import ApprovalRequested, RunEnded, ToolEnded, ToolOutput
from plural.protocol.models import ApprovalDecision
from tests.e2e.support import Watcher, running_session

SLOW = "printf 'one\\ntwo\\n'; sleep 0.3; printf 'three\\n'"
SECRET = "echo token=sk-ant-abcdefghijklmnopqrstuv; sleep 0.2; echo done"


async def approve(owner: Watcher) -> None:
    approval = (await owner.next(ApprovalRequested)).approval
    await owner.client.send(
        ApprovalRespond(approval_id=approval.id, decision=ApprovalDecision.ONCE)
    )


async def test_everyone_sees_command_output_while_it_runs(tmp_path: Path) -> None:
    provider = FakeProvider([use_tool("bash", "c1", command=SLOW), reply("done")])
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        await owner.client.send(PromptSubmit(text="go"))
        await approve(owner)

        first = await guest.next(ToolOutput)
        assert first.call_id == "c1"
        assert first.chunk.startswith("one\ntwo\n")
        ended = await guest.next(ToolEnded)
        assert ended.output == "one\ntwo\nthree\n[exit 0]"
        await owner.next(RunEnded)

        streamed = "".join(e.chunk for e in guest.events if isinstance(e, ToolOutput))
        assert streamed.startswith("one\ntwo\n")


async def test_streamed_output_is_redacted_like_the_final_output(tmp_path: Path) -> None:
    provider = FakeProvider([use_tool("bash", "c1", command=SECRET), reply("done")])
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        await owner.client.send(PromptSubmit(text="go"))
        await approve(owner)
        await owner.next(RunEnded)

        streamed = "".join(e.chunk for e in owner.events if isinstance(e, ToolOutput))
        assert "sk-ant-abcdefghijklmnopqrstuv" not in streamed
        assert "[REDACTED" in streamed or "***" in streamed
