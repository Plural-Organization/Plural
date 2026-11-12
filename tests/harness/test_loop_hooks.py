from pathlib import Path

from tests.doubles import FakeProvider, reply, use_tool
from tests.loop_support import StubGate, collect, make_loop, turn

from plural.agent.loop.events import ToolEnd, ToolStart
from plural.agent.loop.hooks import NoHooks
from plural.agent.providers.base import ToolCallRequest
from plural.protocol.models import Provenance


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
