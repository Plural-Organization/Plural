import asyncio
from pathlib import Path

from tests.doubles import STALL, ScriptedProvider
from tests.loop_support import StubGate, collect, make_loop, turn

from plural.agent.compaction import SUMMARY_PROMPT, extract_summary
from plural.agent.events import AgentEvent, Compacted, MessageEnd, RunEnd
from plural.agent.loop import AgentLoop, LoopLimits
from plural.agent.messages import SUMMARY_HEADER, SummaryTurn, ToolResultTurn
from plural.agent.providers.base import (
    ContextOverflow,
    LlmEvent,
    LLMProvider,
    UsageReport,
)
from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.protocol.models import RunEndReason, Usage

LIMITS = LoopLimits(context_window=1000, compact_at=0.5)


def used(events: tuple[LlmEvent, ...], tokens: int) -> tuple[LlmEvent, ...]:
    return (UsageReport(usage=Usage(input_tokens=tokens)), *events)


def build(tmp_path: Path, provider: LLMProvider) -> AgentLoop:
    return make_loop(tmp_path, provider, StubGate(), LIMITS)


def compacted(events: list[AgentEvent]) -> list[Compacted]:
    return [e for e in events if isinstance(e, Compacted)]


def last(events: list[AgentEvent]) -> RunEnd:
    end = events[-1]
    assert isinstance(end, RunEnd)
    return end


def test_summary_is_extracted_from_its_tags() -> None:
    assert extract_summary("noise <summary>\n goals \n</summary> tail") == "goals"
    assert extract_summary("  plain text ") == "plain text"


async def test_small_prompts_are_never_compacted(tmp_path: Path) -> None:
    provider = FakeProvider([used(use_tool("ls", "c1", path="."), 100), reply("done")])
    events = await collect(build(tmp_path, provider), turn("go"))
    assert compacted(events) == []
    assert len(provider.requests) == 2


async def test_large_prompt_is_summarized_between_tool_rounds(tmp_path: Path) -> None:
    provider = FakeProvider(
        [
            used(use_tool("ls", "c1", path="."), 900),
            reply("<summary>listed the workspace</summary>"),
            reply("finished"),
        ]
    )
    loop = build(tmp_path, provider)
    events = await collect(loop, turn("go"))

    [event] = compacted(events)
    assert event.summary == "listed the workspace"
    assert event.tokens_before == 900
    assert last(events).reason is RunEndReason.STOP

    normal, summarizing, resumed = provider.requests
    assert summarizing.system == normal.system
    assert summarizing.tools == normal.tools
    assert summarizing.messages[-1].content == SUMMARY_PROMPT
    assert any(m.role == "tool" for m in summarizing.messages)

    assert [m.role for m in resumed.messages] == ["user", "user"]
    assert resumed.messages[0].content == f"{SUMMARY_HEADER}\nlisted the workspace"
    assert "go" in resumed.messages[1].content
    assert isinstance(loop.conversation[0], SummaryTurn)
    assert not any(isinstance(m, ToolResultTurn) for m in loop.conversation[:2])


async def test_a_summary_that_calls_tools_is_discarded(tmp_path: Path) -> None:
    provider = FakeProvider(
        [used(use_tool("ls", "c1", path="."), 900), use_tool("ls", "c2", path="."), reply("fine")]
    )
    loop = build(tmp_path, provider)
    events = await collect(loop, turn("go"))

    assert compacted(events) == []
    assert last(events).reason is RunEndReason.STOP
    assert len(provider.requests) == 3
    assert not isinstance(loop.conversation[0], SummaryTurn)


async def test_a_failed_compaction_is_not_retried_every_turn(tmp_path: Path) -> None:
    provider = FakeProvider(
        [
            used(use_tool("ls", "c1", path="."), 900),
            reply(""),
            used(use_tool("ls", "c2", path="./."), 950),
            reply("fine"),
        ]
    )
    events = await collect(build(tmp_path, provider), turn("go"))
    assert compacted(events) == []
    assert len(provider.requests) == 4


async def test_context_overflow_triggers_one_compaction_and_a_retry(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        [ContextOverflow("too long"), reply("<summary>s</summary>"), reply("ok")]
    )
    events = await collect(build(tmp_path, provider), turn("go"))

    assert len(compacted(events)) == 1
    assert last(events).reason is RunEndReason.STOP
    assert any(isinstance(e, MessageEnd) and e.text == "ok" for e in events)


async def test_overflow_after_compaction_ends_the_run(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        [ContextOverflow("too long"), reply("<summary>s</summary>"), ContextOverflow("still")]
    )
    events = await collect(build(tmp_path, provider), turn("go"))
    end = last(events)
    assert end.reason is RunEndReason.ERROR
    assert end.error == "still"


async def test_overflow_without_a_summary_ends_the_run(tmp_path: Path) -> None:
    provider = ScriptedProvider([ContextOverflow("too long"), reply("")])
    end = last(await collect(build(tmp_path, provider), turn("go")))
    assert end.reason is RunEndReason.ERROR
    assert end.error is not None
    assert end.error.startswith("context is full")


async def test_requested_compaction_applies_to_the_next_run(tmp_path: Path) -> None:
    provider = FakeProvider([reply("a"), reply("<summary>S</summary>"), reply("b")])
    loop = build(tmp_path, provider)
    await collect(loop, turn("one"))
    loop.request_compaction()
    events = await collect(loop, turn("two"))

    assert [e.summary for e in compacted(events)] == ["S"]
    assert provider.requests[2].messages[0].content == f"{SUMMARY_HEADER}\nS"
    assert "two" in provider.requests[2].messages[1].content


async def test_nothing_to_summarize_on_a_fresh_conversation(tmp_path: Path) -> None:
    provider = FakeProvider([reply("a")])
    loop = build(tmp_path, provider)
    loop.request_compaction()
    events = await collect(loop, turn("one"))
    assert compacted(events) == []
    assert len(provider.requests) == 1


async def test_restored_summary_seeds_the_conversation(tmp_path: Path) -> None:
    provider = FakeProvider([reply("ok")])
    loop = build(tmp_path, provider)
    loop.restore("earlier work")
    await collect(loop, turn("continue"))
    messages = provider.requests[0].messages
    assert messages[0].content == f"{SUMMARY_HEADER}\nearlier work"
    assert "continue" in messages[1].content


async def test_abort_while_summarizing_ends_the_run(tmp_path: Path) -> None:
    provider = ScriptedProvider([used(use_tool("ls", "c1", path="."), 900), STALL])
    loop = build(tmp_path, provider)
    cancel = asyncio.Event()

    async def drain() -> list[AgentEvent]:
        return [event async for event in loop.run(turn("go"), cancel=cancel)]

    task = asyncio.create_task(drain())
    await asyncio.sleep(0.2)
    cancel.set()
    events = await asyncio.wait_for(task, 2)
    assert last(events).reason is RunEndReason.ABORTED
    assert compacted(events) == []


async def test_compaction_that_cannot_shrink_the_prompt_is_not_repeated(tmp_path: Path) -> None:
    provider = FakeProvider(
        [
            used(use_tool("ls", "c1", path="."), 900),
            reply("<summary>notes</summary>"),
            used(use_tool("ls", "c2", path="./."), 900),
            used(use_tool("ls", "c3", path="././."), 900),
            reply("done"),
        ]
    )
    events = await collect(build(tmp_path, provider), turn("go"))

    assert len(compacted(events)) == 1
    assert last(events).reason is RunEndReason.STOP
    asked = [r for r in provider.requests if r.messages[-1].content == SUMMARY_PROMPT]
    assert len(asked) == 1
