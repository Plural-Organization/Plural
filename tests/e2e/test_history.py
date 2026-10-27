from pathlib import Path

from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.protocol.commands import ApprovalRespond, PromptSubmit
from plural.protocol.events import ApprovalRequested, RunEnded
from plural.protocol.models import ApprovalDecision
from tests.e2e.support import running_session


async def test_a_restarted_host_resumes_the_whole_conversation(tmp_path: Path) -> None:
    provider = FakeProvider(
        [
            use_tool("ls", "c1", path="."),
            reply("I see the workspace"),
            use_tool("bash", "c2", command="echo hi"),
            reply("printed hi"),
        ]
    )
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        await owner.client.send(PromptSubmit(text="look around"))
        await owner.next(RunEnded)
        await guest.client.send(PromptSubmit(text="say hi"))
        approval = await owner.next(ApprovalRequested)
        await owner.client.send(
            ApprovalRespond(approval_id=approval.approval.id, decision=ApprovalDecision.ONCE)
        )
        await owner.next(RunEnded)

    resumed = FakeProvider([reply("welcome back")])
    async with running_session(tmp_path, relayed=False, provider=resumed) as session:
        owner = await session.owner()
        await owner.client.send(PromptSubmit(text="what did we do?"))
        await owner.next(RunEnded)

    messages = resumed.requests[0].messages
    assert [m.role for m in messages] == [
        "user",
        "assistant",
        "tool",
        "assistant",
        "user",
        "assistant",
        "tool",
        "assistant",
        "user",
    ]
    assert "look around" in messages[0].content
    assert messages[1].tool_calls[0].name == "ls"
    assert messages[2].tool_call_id == "c1"
    assert messages[3].content == "I see the workspace"
    assert messages[4].content.startswith("[Alia")
    assert "hi" in messages[6].content
    assert "what did we do?" in messages[8].content
