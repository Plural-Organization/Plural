from pathlib import Path

import pytest

from plural.agent.compaction import SUMMARY_PROMPT
from plural.agent.messages import SUMMARY_HEADER
from plural.agent.providers.base import UsageReport
from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.client.connection import CommandRejected
from plural.protocol.commands import ContextCompact, PromptSubmit
from plural.protocol.events import ContextCompacted, RunEnded
from plural.protocol.models import EntryKind, Usage
from tests.e2e.support import running_session

SMALL_WINDOW = {"context_window": 1000, "compact_at": 0.5}


async def test_automatic_compaction_is_shared_and_survives_a_restart(tmp_path: Path) -> None:
    provider = FakeProvider(
        [
            (UsageReport(usage=Usage(input_tokens=900)), *use_tool("ls", "c1", path=".")),
            reply("<summary>listed the workspace</summary>"),
            reply("all done"),
        ]
    )
    async with running_session(
        tmp_path, relayed=False, provider=provider, overrides=SMALL_WINDOW
    ) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        await owner.client.send(PromptSubmit(text="look around"))
        compacted = await guest.next(ContextCompacted)
        await owner.next(RunEnded)

        assert compacted.summary == "listed the workspace"
        assert compacted.tokens_before == 900
        state = guest.client.projection.state
        assert state.summary == "listed the workspace"
        assert any(entry.kind is EntryKind.COMPACTION for entry in state.transcript)

    resumed = FakeProvider([reply("welcome back")])
    async with running_session(
        tmp_path, relayed=False, provider=resumed, overrides=SMALL_WINDOW
    ) as session:
        owner = await session.owner()
        assert owner.client.projection.state.summary == "listed the workspace"
        await owner.client.send(PromptSubmit(text="continue"))
        await owner.next(RunEnded)
        first = resumed.requests[0].messages
        assert first[0].content == f"{SUMMARY_HEADER}\nlisted the workspace"
        assert "continue" in first[1].content


async def test_host_can_request_compaction_and_guests_cannot(tmp_path: Path) -> None:
    provider = FakeProvider([reply("first"), reply("<summary>S</summary>"), reply("second")])
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        await owner.client.send(PromptSubmit(text="one"))
        await owner.next(RunEnded)

        with pytest.raises(CommandRejected):
            await guest.client.send(ContextCompact())

        await owner.client.send(ContextCompact())
        await owner.client.send(PromptSubmit(text="two"))
        compacted = await owner.next(ContextCompacted)
        assert compacted.summary == "S"
        assert provider.requests[1].messages[-1].content == SUMMARY_PROMPT
