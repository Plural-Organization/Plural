from pathlib import Path

from tests.doubles import FakeProvider, reply, use_tool
from tests.loop_support import StubGate, collect, turn

from plural.agent.context.context import ContextBuilder
from plural.agent.loop.events import ToolEnd, ToolOutput
from plural.agent.loop.loop import AgentLoop
from plural.agent.providers.code_mode import FOLDED, CodeMode
from plural.agent.sandbox.base import Workspace
from plural.agent.sandbox.local import LocalBackend
from plural.agent.tools.base import ToolCtx
from plural.agent.tools.registry import builtin_tools
from plural.host.system import UlidGenerator

CODE = """
import asyncio
a, b = await asyncio.gather(read(path="a.txt"), read(path="b.txt"))
await write(path="c.txt", content="gamma")
{"a": "alpha" in a, "b": "beta" in b}
"""


async def folded_loop(
    tmp_path: Path, provider: FakeProvider, gate: StubGate
) -> tuple[AgentLoop, CodeMode]:
    (tmp_path / "a.txt").write_text("alpha\n")
    (tmp_path / "b.txt").write_text("beta\n")
    tools = builtin_tools()
    code_mode = CodeMode(tools)
    await code_mode.start()
    tools.fold(FOLDED)
    tools.add_source(code_mode)
    loop = AgentLoop(
        provider=provider,
        tools=tools,
        gate=gate,
        context=ContextBuilder(tool_rules=tools.guidelines()),
        tool_ctx=ToolCtx(workspace=Workspace.at(tmp_path), backend=LocalBackend()),
        ids=UlidGenerator(),
    )
    return loop, code_mode


async def test_the_code_calls_the_folded_tools_and_each_call_is_checked(tmp_path: Path) -> None:
    provider = FakeProvider([use_tool("run_code", code=CODE), reply("done")])
    gate = StubGate()
    loop, code_mode = await folded_loop(tmp_path, provider, gate)
    try:
        events = await collect(loop, turn("go"))
    finally:
        await code_mode.close()

    declared = {schema.name for schema in provider.requests[0].tools}
    assert "run_code" in declared
    assert "bash" in declared
    assert declared.isdisjoint(FOLDED)
    assert "async def read(" in next(
        schema.description for schema in provider.requests[0].tools if schema.name == "run_code"
    )

    [end] = [event for event in events if isinstance(event, ToolEnd)]
    assert not end.result.is_error
    assert end.result.content == '{"a": true, "b": true}'
    assert (tmp_path / "c.txt").read_text() == "gamma"
    # The gate saw the code's call and each of the three it made.
    assert sorted(subject for subject, _ in gate.seen)[:3] == ["a.txt", "b.txt", "c.txt"]
    assert len(gate.seen) == 4
    shown = "".join(event.chunk for event in events if isinstance(event, ToolOutput))
    assert "read a.txt" in shown
    assert "write c.txt" in shown


async def test_a_failed_call_raises_in_the_code_and_a_denied_one_changes_nothing(
    tmp_path: Path,
) -> None:
    caught = 'try:\n    await read(path="missing.txt")\nexcept Exception:\n    out = "caught"\nout'
    provider = FakeProvider(
        [use_tool("run_code", code=caught), use_tool("run_code", code="1 +"), reply("done")]
    )
    loop, code_mode = await folded_loop(tmp_path, provider, StubGate())
    try:
        events = await collect(loop, turn("go"))
    finally:
        await code_mode.close()
    first, second = [event for event in events if isinstance(event, ToolEnd)]
    assert first.result.content == "caught"
    assert second.result.is_error


FIND = """
found = await search_tools(query="edit several places in one file")
names = [tool["name"] for tool in found]
described = await describe_tool(name="multi_edit")
await multi_edit(path="a.txt", edits=[{"old": "alpha", "new": "omega"}])
{"found": "multi_edit" in names, "described": "async def multi_edit(" in described}
"""


async def test_the_code_finds_and_calls_a_tool_the_model_was_never_shown(tmp_path: Path) -> None:
    provider = FakeProvider(
        [use_tool("run_code", code=FIND), use_tool("run_code", code="1"), reply("done")]
    )
    loop, code_mode = await folded_loop(tmp_path, provider, StubGate())
    try:
        events = await collect(loop, turn("go"))
    finally:
        await code_mode.close()

    first = next(event for event in events if isinstance(event, ToolEnd))
    assert first.result.content == '{"found": true, "described": true}'
    assert (tmp_path / "a.txt").read_text() == "omega\n"
    # Called from code, the deferred tool is still not declared to the model.
    assert "multi_edit" not in {schema.name for schema in provider.requests[-1].tools}
    description = next(s for s in provider.requests[0].tools if s.name == "run_code").description
    assert "async def multi_edit(" not in description
    assert "search_tools()" in description


async def test_a_failing_command_returns_its_output_to_the_code(tmp_path: Path) -> None:
    code = 'out = await bash(command="echo broken; exit 3")\n"[exit 3]" in out and "broken" in out'
    provider = FakeProvider([use_tool("run_code", code=code), reply("done")])
    loop, code_mode = await folded_loop(tmp_path, provider, StubGate())
    try:
        events = await collect(loop, turn("go"))
    finally:
        await code_mode.close()
    end = next(event for event in events if isinstance(event, ToolEnd))
    assert end.result.content == "true"
