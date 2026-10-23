import asyncio
from pathlib import Path

import pytest

from plural.agent.context import ContextBuilder
from plural.agent.events import AgentEvent, RunEnd, ToolEnd
from plural.agent.gate import GateResult
from plural.agent.loop import AgentLoop, LoopLimits
from plural.agent.messages import ToolResultTurn, UserTurn, attribute
from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.agent.sandbox.base import Workspace
from plural.agent.sandbox.local import LocalBackend
from plural.agent.tools.base import ToolCtx
from plural.agent.tools.registry import builtin_tools
from plural.core.provenance import direct, from_proposal
from plural.host.system import UlidGenerator
from plural.protocol.models import Actor, ActorKind, Provenance, Role, RunEndReason, ToolCallView


class StubGate:
    def __init__(self, *, allowed: bool = True, block: bool = False) -> None:
        self.allowed = allowed
        self.block = block
        self.seen: list[tuple[str, Provenance]] = []

    async def check(
        self, call: ToolCallView, *, subject: str, provenance: Provenance
    ) -> GateResult:
        self.seen.append((subject, provenance))
        if self.block:
            await asyncio.Event().wait()
        return GateResult(allowed=self.allowed, reason="stub")


def turn(text: str, *, guest: bool = False) -> UserTurn:
    provenance = from_proposal("p_alia", Role.PARTICIPANT) if guest else direct("p_host", Role.HOST)
    name = "Alia" if guest else "Host"
    actor = Actor(id=provenance.initiator_id, kind=ActorKind.HUMAN, name=name)
    return UserTurn(id=f"pm_{text}", author=actor, provenance=provenance, text=text)


def make_loop(
    tmp_path: Path, provider: FakeProvider, gate: StubGate, limits: LoopLimits | None = None
) -> AgentLoop:
    (tmp_path / "a.txt").write_text("alpha\n")
    return AgentLoop(
        provider=provider,
        tools=builtin_tools(),
        gate=gate,
        context=ContextBuilder(),
        tool_ctx=ToolCtx(workspace=Workspace.at(tmp_path), backend=LocalBackend()),
        ids=UlidGenerator(),
        limits=limits,
    )


async def collect(loop: AgentLoop, prompt: UserTurn) -> list[AgentEvent]:
    return [event async for event in loop.run(prompt, cancel=asyncio.Event())]


async def test_tool_call_then_answer(tmp_path: Path) -> None:
    provider = FakeProvider([use_tool("read", path="a.txt"), reply("done")])
    events = await collect(make_loop(tmp_path, provider, StubGate()), turn("read it"))
    tool_end = next(e for e in events if isinstance(e, ToolEnd))
    assert "alpha" in tool_end.result.content
    last = events[-1]
    assert isinstance(last, RunEnd)
    assert last.reason is RunEndReason.STOP
    assert provider.requests[1].messages[-1].role == "tool"


async def test_denial_is_reported_to_model(tmp_path: Path) -> None:
    provider = FakeProvider([use_tool("bash", command="pytest"), reply("ok")])
    loop = make_loop(tmp_path, provider, StubGate(allowed=False))
    await collect(loop, turn("test"))
    result = next(m for m in loop.conversation if isinstance(m, ToolResultTurn))
    assert result.is_error
    assert result.content.startswith("Denied")


async def test_repeated_call_stops(tmp_path: Path) -> None:
    provider = FakeProvider([use_tool("ls", path=".")] * 5)
    events = await collect(make_loop(tmp_path, provider, StubGate()), turn("loop"))
    last = events[-1]
    assert isinstance(last, RunEnd)
    assert last.reason is RunEndReason.LIMIT


async def test_max_turns(tmp_path: Path) -> None:
    provider = FakeProvider([use_tool("ls", f"c{i}", path="." + "/." * i) for i in range(3)])
    events = await collect(
        make_loop(tmp_path, provider, StubGate(), LoopLimits(max_turns=2, repeat_limit=10)),
        turn("x"),
    )
    last = events[-1]
    assert isinstance(last, RunEnd)
    assert last.error == "max turns reached"


async def test_guest_steer_taints_provenance(tmp_path: Path) -> None:
    provider = FakeProvider(
        [use_tool("ls", "c1", path="."), use_tool("bash", "c2", command="ls"), reply("ok")]
    )
    gate = StubGate()
    loop = make_loop(tmp_path, provider, gate)
    loop.steer(turn("also check", guest=True))
    await collect(loop, turn("start"))
    assert gate.seen[0][1].initiator_role is Role.HOST
    assert gate.seen[1][1].initiator_role is Role.PARTICIPANT
    assert "[Alia, proposal approved by host]" in provider.requests[1].messages[-1].content


async def test_cancel_settles_conversation(tmp_path: Path) -> None:
    provider = FakeProvider([use_tool("bash", command="make")])
    loop = make_loop(tmp_path, provider, StubGate(block=True))
    task = asyncio.create_task(collect(loop, turn("go")))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    last = loop.conversation[-1]
    assert isinstance(last, ToolResultTurn)
    assert last.is_error


def test_attribution() -> None:
    assert attribute(turn("hi")) == "[Host]\nhi"
