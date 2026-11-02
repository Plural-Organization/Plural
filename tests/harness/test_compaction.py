import asyncio
from pathlib import Path

from tests.doubles import STALL, ScriptedProvider
from tests.loop_support import StubGate, collect, make_loop, turn

from plural.agent.compaction import SUMMARY_PROMPT, SUMMARY_SYSTEM, extract_summary
from plural.agent.events import AgentEvent, Compacted, MessageEnd, RunEnd
from plural.agent.loop import FALLBACK_WINDOW, AgentLoop, LoopLimits
from plural.agent.messages import (
    AssistantTurn,
    SummaryTurn,
    ToolResultTurn,
    UserTurn,
    summary_message,
)
from plural.agent.providers.base import (
    ContextOverflow,
    LlmEvent,
    LLMProvider,
    NativeContent,
    Stop,
    TextDelta,
    ToolCallRequest,
    UsageReport,
)
from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.protocol.models import RunEndReason, Usage

LIMITS = LoopLimits(context_window=1000, compact_reserve=500)


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
    # The reported 900, plus an estimate of the tool round that came after it.
    assert 900 < event.tokens_before < 950
    assert last(events).reason is RunEndReason.STOP

    _, summarizing, resumed = provider.requests
    # The summary is asked for on its own: no tools, the conversation written out as text.
    assert summarizing.system == SUMMARY_SYSTEM
    assert summarizing.tools == ()
    [asked] = summarizing.messages
    assert asked.content.endswith(SUMMARY_PROMPT)
    assert "[ls result]" in asked.content

    assert [m.role for m in resumed.messages] == ["user", "user"]
    assert resumed.messages[0].content == summary_message("listed the workspace")
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
    assert provider.requests[2].messages[0].content == summary_message("S")
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
    loop.restore([SummaryTurn(text="earlier work")])
    await collect(loop, turn("continue"))
    messages = provider.requests[0].messages
    assert messages[0].content == summary_message("earlier work")
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
    asked = [r for r in provider.requests if r.system == SUMMARY_SYSTEM]
    assert len(asked) == 1


async def test_tool_output_after_the_last_report_counts_toward_the_threshold(
    tmp_path: Path,
) -> None:
    (tmp_path / "big.txt").write_text("word " * 800)
    provider = FakeProvider(
        [
            used(use_tool("read", "c1", path="big.txt"), 300),
            reply("<summary>read the big file</summary>"),
            reply("done"),
        ]
    )
    events = await collect(build(tmp_path, provider), turn("go"))
    # The provider counted 300, but the file read after it pushes the prompt past 500.
    [event] = compacted(events)
    assert event.tokens_before > 500


class WindowedProvider(FakeProvider):
    """A provider that says how big its model's window is, as the real ones do."""

    def __init__(self, window: int, script: list[tuple[LlmEvent, ...]]) -> None:
        super().__init__(script)
        self.window = window

    async def context_window(self) -> int | None:
        return self.window


async def test_the_window_comes_from_the_provider(tmp_path: Path) -> None:
    provider = WindowedProvider(
        1000,
        [
            used(use_tool("ls", "c1", path="."), 900),
            reply("<summary>listed</summary>"),
            reply("done"),
        ],
    )
    loop = make_loop(tmp_path, provider, StubGate(), LoopLimits(compact_reserve=200))
    events = await collect(loop, turn("go"))
    assert len(compacted(events)) == 1
    fill = loop.fill()
    assert (fill.window, fill.compact_at) == (1000, 0.8)


async def test_a_provider_without_a_window_gets_the_fallback(tmp_path: Path) -> None:
    provider = FakeProvider([used(use_tool("ls", "c1", path="."), 900), reply("done")])
    loop = make_loop(tmp_path, provider, StubGate(), LoopLimits())
    events = await collect(loop, turn("go"))
    assert compacted(events) == []
    assert loop.fill().window == FALLBACK_WINDOW


async def test_nothing_is_summarized_before_the_window_is_known(tmp_path: Path) -> None:
    # A resumed session may be long; until the first call says how big the window is, the
    # conversation is left alone unless the provider says it overflows.
    provider = WindowedProvider(1_000_000, [reply("still here")])
    loop = make_loop(tmp_path, provider, StubGate(), LoopLimits())
    loop.restore([turn("x" * 600_000), AssistantTurn(text="ok")])
    events = await collect(loop, turn("go"))
    assert compacted(events) == []
    assert loop.fill().window == 1_000_000


async def test_the_newest_turns_are_kept_and_their_thinking_is_dropped(tmp_path: Path) -> None:
    native = NativeContent(provider="anthropic", blocks=({"type": "thinking", "signature": "s"},))
    ls = ToolCallRequest(id="c1", name="ls", args={"path": "."})
    loop = make_loop(
        tmp_path,
        FakeProvider([reply("<summary>talked about a</summary>"), reply("done")]),
        StubGate(),
        LoopLimits(context_window=1000, compact_reserve=500, keep_recent=120),
    )
    loop.restore(
        [
            turn("first question"),
            AssistantTurn(text="a" * 2400),
            turn("second question"),
            AssistantTurn(tool_calls=(ls,), native=native),
            ToolResultTurn(call_id="c1", name="ls", content="x" * 200),
        ]
    )
    events = await collect(loop, turn("third question"))

    [event] = compacted(events)
    assert event.kept_from == "prompt:pm_second question"
    summary, second, call, result, third, _ = loop.conversation
    assert isinstance(summary, SummaryTurn)
    assert isinstance(second, UserTurn)
    assert second.text == "second question"
    assert isinstance(call, AssistantTurn)
    assert call.tool_calls == (ls,)
    assert call.native is None
    assert isinstance(result, ToolResultTurn)
    assert isinstance(third, UserTurn)
    assert third.text == "third question"


async def test_a_run_cut_in_the_middle_keeps_its_prompt_and_latest_round(tmp_path: Path) -> None:
    (tmp_path / "big.txt").write_text("word " * 240)
    provider = FakeProvider(
        [
            used(use_tool("read", "c1", path="big.txt"), 100),
            used(use_tool("ls", "c2", path="."), 600),
            reply("<summary>read big.txt</summary>"),
            reply("done"),
        ]
    )
    limits = LoopLimits(context_window=1000, compact_reserve=500, keep_recent=100)
    loop = make_loop(tmp_path, provider, StubGate(), limits)
    events = await collect(loop, turn("go"))

    [event] = compacted(events)
    assert event.kept_from == "call:c2"
    resumed = provider.requests[-1]
    assert [message.role for message in resumed.messages] == ["user", "user", "assistant", "tool"]
    assert resumed.messages[0].content == summary_message(
        "read big.txt\n\n<read-files>\nbig.txt\n</read-files>"
    )
    assert resumed.messages[1].content.endswith("go")
    assert resumed.messages[2].tool_calls[0].id == "c2"


async def test_a_second_compaction_updates_the_first_summary(tmp_path: Path) -> None:
    provider = FakeProvider([reply("<summary>newer</summary>"), reply("done")])
    loop = build(tmp_path, provider)
    earlier = "older work\n\n<modified-files>\nold.py\n</modified-files>"
    loop.restore([SummaryTurn(text=earlier), turn("x" * 2400), AssistantTurn(text="ok")])
    events = await collect(loop, turn("go on"))

    [event] = compacted(events)
    [asked] = provider.requests[0].messages
    assert "<previous_summary>\nolder work\n</previous_summary>" in asked.content
    assert event.summary == "newer\n\n<modified-files>\nold.py\n</modified-files>"


async def test_a_summary_cut_off_at_the_output_limit_is_not_used(tmp_path: Path) -> None:
    main = FakeProvider(
        [
            used(use_tool("ls", "c1", path="."), 900),
            reply("<summary>whole summary</summary>"),
            reply("finished"),
        ]
    )
    fast = FakeProvider([(TextDelta(text="<summary>half"), Stop(reason="max_tokens"))])
    loop = make_loop(tmp_path, main, StubGate(), LIMITS, helper=fast)
    events = await collect(loop, turn("go"))
    assert [event.summary for event in compacted(events)] == ["whole summary"]
