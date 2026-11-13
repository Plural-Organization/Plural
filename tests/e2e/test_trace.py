from pathlib import Path

from plural.agent.providers.base import LlmEvent, Stop, ToolCallReady, ToolCallRequest, UsageReport
from plural.protocol.commands import PromptSubmit, TraceGet
from plural.protocol.events import RunEnded, TraceFound
from plural.protocol.models import Span, SpanKind, SpanStatus, Usage
from tests.doubles import FakeProvider, reply, use_tool
from tests.e2e.support import running_session


def delegate(task: str) -> tuple[LlmEvent, ...]:
    call = ToolCallRequest(id="d1", name="agent", args={"agent": "explore", "task": task})
    return (
        UsageReport(usage=Usage(input_tokens=300, output_tokens=20)),
        ToolCallReady(call=call),
        Stop(reason="tool_use"),
    )


def under(spans: tuple[Span, ...], parent: Span) -> list[Span]:
    return [span for span in spans if span.parent_id == parent.id]


async def test_a_guest_sees_what_a_run_did_and_what_each_part_spent(tmp_path: Path) -> None:
    provider = FakeProvider(
        [
            delegate("look around"),
            (
                UsageReport(usage=Usage(input_tokens=40, output_tokens=5)),
                *use_tool("ls", "l1", path="."),
            ),
            reply("notes.txt is here"),
            (UsageReport(usage=Usage(input_tokens=500, output_tokens=30)), *reply("done")),
        ]
    )
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        await owner.client.send(PromptSubmit(text="what is here?"))
        ended = await guest.next(RunEnded)

        await guest.client.send(TraceGet())
        found = await guest.next(TraceFound)

        assert found.run_id == ended.run_id
        assert [run.run_id for run in found.runs] == [ended.run_id]
        assert all(span.run_id == ended.run_id for span in found.spans)
        (run,) = [span for span in found.spans if span.parent_id is None]
        assert (run.kind, run.status, run.detail) == (SpanKind.RUN, SpanStatus.OK, "what is here?")
        # The run is the prompter's.
        me = owner.client.projection.me
        assert me is not None
        assert run.actor_id == me.id
        kinds = [(span.kind, span.name) for span in under(found.spans, run)]
        assert kinds == [
            (SpanKind.LLM, "turn"),
            (SpanKind.AGENT, "explore"),
            (SpanKind.LLM, "turn"),
        ]
        first, agent, last = under(found.spans, run)
        assert (first.usage.input_tokens, last.usage.input_tokens) == (300, 500)
        # A role is named by the model this host runs for it.
        assert first.model
        assert first.model not in {"main", "fast"}
        inside = [(span.kind, span.name) for span in under(found.spans, agent)]
        assert inside == [(SpanKind.LLM, "turn"), (SpanKind.TOOL, "ls"), (SpanKind.LLM, "turn")]
        assert under(found.spans, agent)[0].usage.input_tokens == 40
        assert all(span.ended_ms is not None for span in found.spans)

        # A guest sees what tools got and gave, and what the model answered, not what it was sent.
        assert all(span.input == "" for span in found.spans if span.kind is SpanKind.LLM)
        assert all(span.output for span in found.spans if span.kind is SpanKind.LLM)
        await owner.client.send(TraceGet())
        mine = await owner.next(TraceFound)
        assert all(span.input for span in mine.spans if span.kind is SpanKind.LLM)

        await guest.client.send(TraceGet(everything=True))
        everything = await guest.next(TraceFound)
        assert everything.run_id is None
        assert len(everything.spans) == len(found.spans)
