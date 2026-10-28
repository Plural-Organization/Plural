from pathlib import Path

from plural.agent.providers.base import LlmEvent, Stop, ToolCallReady, ToolCallRequest
from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.protocol.commands import PromptSubmit
from plural.protocol.events import ApprovalRequested, RunEnded, ToolEnded, ToolOutput
from tests.e2e.support import running_session


def delegate(task: str) -> tuple[LlmEvent, ...]:
    call = ToolCallRequest(id="d1", name="agent", args={"agent": "explore", "task": task})
    return ToolCallReady(call=call), Stop(reason="tool_use")


async def test_a_guest_can_send_explore_and_secrets_stay_closed(tmp_path: Path) -> None:
    provider = FakeProvider(
        [
            delegate("read the notes and the env file"),
            use_tool("read", "r1", path="notes.txt"),
            use_tool("read", "r2", path=".env"),
            reply("notes say alpha and beta; .env was denied"),
            reply("explore says: alpha and beta"),
        ]
    )
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        (tmp_path / "ws" / ".env").write_text("TOKEN=shh\n")
        owner = await session.owner()
        guest = await session.guest("Alia")

        await guest.client.send(PromptSubmit(text="what is in the notes?"))
        ended = await owner.next(ToolEnded)
        await owner.next(RunEnded)

        assert ended.call_id == "d1"
        assert ended.ok
        assert ended.output.startswith("notes say alpha and beta")
        progress = "".join(e.chunk for e in owner.events if isinstance(e, ToolOutput))
        assert "· read notes.txt" in progress
        assert "✗ Denied" in progress
        assert not any(isinstance(event, ApprovalRequested) for event in owner.events)
        assert "shh" not in str(provider.requests)
