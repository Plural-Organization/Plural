from pathlib import Path

from tests.loop_support import StubGate, collect, make_loop, turn

from plural.agent.compaction import SUMMARY_PROMPT
from plural.agent.events import AgentEvent, Compacted
from plural.agent.loop import LoopLimits
from plural.agent.providers.base import LlmEvent, UsageReport
from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.protocol.models import Usage

LIMITS = LoopLimits(context_window=1000, compact_at=0.5)


def used(events: tuple[LlmEvent, ...], tokens: int) -> tuple[LlmEvent, ...]:
    return (UsageReport(usage=Usage(input_tokens=tokens)), *events)


def summaries(events: list[AgentEvent]) -> list[str]:
    return [event.summary for event in events if isinstance(event, Compacted)]


async def test_the_fast_model_writes_the_summary_when_there_is_one(tmp_path: Path) -> None:
    main = FakeProvider([used(use_tool("ls", "c1", path="."), 900), reply("finished")])
    fast = FakeProvider([reply("<summary>listed the workspace cheaply</summary>")])
    loop = make_loop(tmp_path, main, StubGate(), LIMITS, helper=fast)

    events = await collect(loop, turn("look around"))

    assert summaries(events) == ["listed the workspace cheaply"]
    assert fast.requests[0].messages[-1].content == SUMMARY_PROMPT
    assert all(request.messages[-1].content != SUMMARY_PROMPT for request in main.requests)


async def test_the_main_model_takes_over_when_the_fast_one_fails(tmp_path: Path) -> None:
    main = FakeProvider(
        [
            used(use_tool("ls", "c1", path="."), 900),
            reply("<summary>main summary</summary>"),
            reply("finished"),
        ]
    )
    fast = FakeProvider([reply("")])
    loop = make_loop(tmp_path, main, StubGate(), LIMITS, helper=fast)

    events = await collect(loop, turn("look around"))

    assert summaries(events) == ["main summary"]
    assert len(fast.requests) == 1
