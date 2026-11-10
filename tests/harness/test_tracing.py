import asyncio
from pathlib import Path

from tests.doubles import FakeProvider, ScriptedProvider, reply, use_tool
from tests.harness.test_subagents import build, delegate
from tests.loop_support import StubGate, collect, make_loop, turn

from plural.agent.loop.gate import GateResult
from plural.agent.providers.base import UsageReport
from plural.protocol.models import (
    Provenance,
    Span,
    SpanKind,
    SpanStatus,
    ToolCallView,
    Usage,
)


def tree(spans: tuple[Span, ...]) -> dict[str, list[Span]]:
    """Each span's children, by its id; the roots are under ""."""
    children: dict[str, list[Span]] = {}
    for span in spans:
        children.setdefault(span.parent_id or "", []).append(span)
    return children


async def test_a_run_is_a_tree_of_its_model_and_tool_calls(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("alpha\n")
    usage = Usage(input_tokens=100, cache_read_tokens=300, output_tokens=7)
    provider = ScriptedProvider(
        [
            (UsageReport(usage=usage), *use_tool("read", "c1", path="a.txt")),
            (UsageReport(usage=usage), *reply("done")),
        ]
    )
    loop = make_loop(tmp_path, provider, StubGate())
    await collect(loop, turn("read  the\nfile"))

    spans = loop.tracer.take()
    children = tree(spans)
    (run,) = children[""]
    assert (run.kind, run.name, run.detail, run.status) == (
        SpanKind.RUN,
        "run",
        "read the file",
        SpanStatus.OK,
    )
    assert [(s.kind, s.name) for s in children[run.id]] == [
        (SpanKind.LLM, "turn"),
        (SpanKind.TOOL, "read"),
        (SpanKind.LLM, "turn"),
    ]
    first, tool, _ = children[run.id]
    assert first.usage == usage
    assert first.context_tokens == 400
    assert first.model == "main"
    assert (tool.detail, tool.status) == ("a.txt", SpanStatus.OK)
    assert tool.chars > 0
    assert all(span.ended_ms is not None and span.ended_ms >= span.started_ms for span in spans)
    # A span the host already took is not handed out again until it changes.
    assert loop.tracer.take() == ()


async def test_a_sub_agents_work_shows_under_the_call_that_started_it(tmp_path: Path) -> None:
    main = FakeProvider([delegate("explore", "where is alpha?"), reply("alpha lives in a.txt")])
    fast = FakeProvider([use_tool("grep", "g1", pattern="alpha"), reply("alpha is at a.txt:1")])
    loop = build(tmp_path, main, fast, StubGate())
    await collect(loop, turn("find alpha"))

    children = tree(loop.tracer.take())
    (run,) = children[""]
    agent = next(span for span in children[run.id] if span.kind is SpanKind.AGENT)
    assert (agent.name, agent.model, agent.detail) == ("explore", "fast", "where is alpha?")
    inside = [(span.kind, span.name, span.model) for span in children[agent.id]]
    assert inside == [
        (SpanKind.LLM, "turn", "fast"),
        (SpanKind.TOOL, "grep", ""),
        (SpanKind.LLM, "turn", "fast"),
    ]


class AskingGate(StubGate):
    """Answers after a wait, as a host who was asked."""

    async def check(
        self, call: ToolCallView, *, subject: str, provenance: Provenance
    ) -> GateResult:
        await asyncio.sleep(0.05)
        return GateResult(allowed=self.allowed, reason="stub", asked=True)


async def test_the_wait_for_approval_is_a_span_of_its_own(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("alpha\n")
    provider = FakeProvider([use_tool("read", "c1", path="a.txt"), reply("done")])
    loop = make_loop(tmp_path, provider, AskingGate(allowed=False))
    await collect(loop, turn("go"))

    spans = loop.tracer.take()
    tool = next(span for span in spans if span.kind is SpanKind.TOOL)
    approval = next(span for span in spans if span.kind is SpanKind.APPROVAL)
    assert tool.status is SpanStatus.DENIED
    assert approval.parent_id == tool.id
    assert approval.ended_ms is not None
    assert approval.ended_ms - approval.started_ms >= 40
    assert tool.started_ms <= approval.started_ms
