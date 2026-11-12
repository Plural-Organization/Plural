from pathlib import Path

from tests.doubles import FakeProvider, reply, use_tool
from tests.loop_support import StubGate, collect, make_loop, turn

from plural.agent.loop.events import ToolEnd, ToolStart
from plural.agent.loop.hooks import NoHooks
from plural.agent.loop.messages import ToolResultTurn
from plural.agent.providers.base import ToolCallRequest
from plural.agent.tools.base import ToolResult
from plural.protocol.models import Provenance, ToolCallView


class Redirect(NoHooks):
    """Reads b.txt whenever the model asks for a.txt."""

    async def tool_args(self, call: ToolCallRequest, provenance: Provenance) -> ToolCallRequest:
        if call.args.get("path") == "a.txt":
            return call.model_copy(update={"args": {**call.args, "path": "b.txt"}})
        return call


async def test_the_hooks_change_a_calls_arguments_before_it_runs(tmp_path: Path) -> None:
    (tmp_path / "b.txt").write_text("beta\n")
    provider = FakeProvider([use_tool("read", path="a.txt"), reply("done")])
    gate = StubGate()
    events = await collect(make_loop(tmp_path, provider, gate, hooks=Redirect()), turn("read"))

    start = next(e for e in events if isinstance(e, ToolStart))
    assert start.call.args == {"path": "b.txt"}
    assert start.call.subject == "b.txt"
    end = next(e for e in events if isinstance(e, ToolEnd))
    assert "beta" in end.result.content


class Shout(NoHooks):
    async def tool_result(
        self, call: ToolCallView, result: ToolResult, provenance: Provenance
    ) -> ToolResult:
        return ToolResult(f"{call.name}: {result.content.upper()}", is_error=result.is_error)


async def test_the_hooks_change_what_a_call_gives_back(tmp_path: Path) -> None:
    provider = FakeProvider([use_tool("read", path="a.txt"), reply("done")])
    loop = make_loop(tmp_path, provider, StubGate(), hooks=Shout())
    events = await collect(loop, turn("read"))

    end = next(e for e in events if isinstance(e, ToolEnd))
    assert end.result.content.startswith("read: ")
    assert "ALPHA" in end.result.content
    kept = next(m for m in loop.conversation if isinstance(m, ToolResultTurn))
    assert kept.content == end.result.content
