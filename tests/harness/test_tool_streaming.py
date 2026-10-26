from pathlib import Path

from tests.loop_support import StubGate, collect, make_loop, turn

from plural.agent.events import RunEnd, ToolEnd, ToolOutput, ToolStart
from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.protocol.models import RunEndReason

SLOW = "printf 'one\\ntwo\\n'; sleep 0.25; printf 'three\\n'; sleep 0.25; printf 'four'"


async def test_bash_output_reaches_the_loop_while_the_command_runs(tmp_path: Path) -> None:
    provider = FakeProvider([use_tool("bash", "c1", command=SLOW), reply("done")])
    events = await collect(make_loop(tmp_path, provider, StubGate()), turn("go"))

    kinds = [type(e).__name__ for e in events]
    assert kinds.index("ToolStart") < kinds.index("ToolOutput") < kinds.index("ToolEnd")

    chunks = [e for e in events if isinstance(e, ToolOutput)]
    assert chunks
    assert all(chunk.call_id == "c1" for chunk in chunks)
    assert "".join(chunk.chunk for chunk in chunks).startswith("one\ntwo\n")

    end = next(e for e in events if isinstance(e, ToolEnd))
    assert end.result.content == "one\ntwo\nthree\nfour\n[exit 0]"
    last = events[-1]
    assert isinstance(last, RunEnd)
    assert last.reason is RunEndReason.STOP


async def test_streamed_chunks_are_whole_lines(tmp_path: Path) -> None:
    provider = FakeProvider([use_tool("bash", "c1", command=SLOW), reply("done")])
    events = await collect(make_loop(tmp_path, provider, StubGate()), turn("go"))
    chunks = [e.chunk for e in events if isinstance(e, ToolOutput)]
    assert all(chunk.endswith("\n") for chunk in chunks)
    assert "four" not in "".join(chunks)


async def test_tools_without_output_emit_nothing(tmp_path: Path) -> None:
    provider = FakeProvider([use_tool("read", "c1", path="a.txt"), reply("done")])
    events = await collect(make_loop(tmp_path, provider, StubGate()), turn("read"))
    assert not any(isinstance(e, ToolOutput) for e in events)
    assert any(isinstance(e, ToolStart) for e in events)


async def test_a_denied_command_streams_nothing(tmp_path: Path) -> None:
    provider = FakeProvider([use_tool("bash", "c1", command=SLOW), reply("done")])
    events = await collect(make_loop(tmp_path, provider, StubGate(allowed=False)), turn("go"))
    assert not any(isinstance(e, ToolOutput) for e in events)
    end = next(e for e in events if isinstance(e, ToolEnd))
    assert end.result.is_error
