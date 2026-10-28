from pathlib import Path

import pytest

from plural.agent.compaction import SUMMARY_PROMPT
from plural.agent.messages import SUMMARY_HEADER
from plural.agent.providers.base import UsageReport
from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.client.connection import CommandRejected
from plural.protocol.commands import ContextCompact, PromptSubmit
from plural.protocol.events import ContextCompacted, ContextCompacting, ContextUsage, RunEnded
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
        assert "look around" in first[1].content
        assert (first[2].role, first[2].content) == ("assistant", "all done")
        assert "continue" in first[3].content


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


async def test_an_idle_compaction_runs_now_and_everyone_watches_it(tmp_path: Path) -> None:
    provider = FakeProvider(
        [
            (UsageReport(usage=Usage(input_tokens=400)), *reply("first")),
            reply("<summary>talked about the repo</summary>"),
        ]
    )
    async with running_session(
        tmp_path, relayed=False, provider=provider, overrides=SMALL_WINDOW
    ) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        await owner.client.send(PromptSubmit(text="one"))
        usage = await guest.next(ContextUsage)
        assert (usage.context.tokens, usage.context.window) == (400, 1000)
        await guest.next(RunEnded)

        await owner.client.send(ContextCompact())
        compacting = await guest.next(ContextCompacting)
        assert compacting.tokens_before == 400
        assert (await guest.next(ContextCompacted)).summary == "talked about the repo"
        after = await guest.next(ContextUsage)
        assert after.context.tokens < 400
        ended = await guest.next(RunEnded)
        assert ended.error is None
        assert guest.client.projection.state.context == after.context


async def test_there_is_nothing_to_compact_in_a_new_session(tmp_path: Path) -> None:
    async with running_session(tmp_path, relayed=False, provider=FakeProvider()) as session:
        owner = await session.owner()
        with pytest.raises(CommandRejected) as rejected:
            await owner.client.send(ContextCompact())
        assert "nothing to compact" in rejected.value.error.message
