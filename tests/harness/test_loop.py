import asyncio
import itertools
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from tests.doubles import StallingProvider

from plural.agent.context import ContextBuilder
from plural.agent.events import AgentEvent, MessageEnd, RunEnd, ToolEnd, ToolStart
from plural.agent.gate import GateResult
from plural.agent.loop import AgentLoop, LoopLimits
from plural.agent.messages import AssistantTurn, ToolResultTurn, UserTurn, attribute
from plural.agent.providers.base import (
    LlmEvent,
    LLMProvider,
    LlmRequest,
    NativeContent,
    NativeReady,
    ProviderError,
    Stop,
    TextDelta,
    ToolCallReady,
    ToolCallRequest,
)
from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.agent.sandbox.base import Workspace
from plural.agent.sandbox.local import LocalBackend
from plural.agent.tools.base import ToolCtx
from plural.agent.tools.registry import builtin_tools
from plural.core.provenance import direct, from_proposal
from plural.host.system import UlidGenerator
from plural.protocol.models import (
    Actor,
    ActorKind,
    Provenance,
    Role,
    RunEndReason,
    ToolCallView,
)


class StubGate:
    def __init__(self, *, allowed: bool = True, block: bool = False) -> None:
        self.allowed = allowed
        self.block = block
        self.runs = 0
        self.seen: list[tuple[str, Provenance]] = []

    def begin_run(self) -> None:
        self.runs += 1

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
    tmp_path: Path, provider: LLMProvider, gate: StubGate, limits: LoopLimits | None = None
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


class FailingProvider:
    async def stream(
        self, request: LlmRequest, *, cancel: asyncio.Event
    ) -> AsyncIterator[LlmEvent]:
        yield TextDelta(text="partial")
        raise ProviderError("anthropic 529: overloaded")


async def test_truncated_tool_calls_are_not_executed(tmp_path: Path) -> None:
    truncated = (
        ToolCallReady(call=ToolCallRequest(id="c1", name="write", args={"path": "a.txt"})),
        Stop(reason="max_tokens"),
    )
    provider = FakeProvider([truncated, reply("retrying smaller")])
    gate = StubGate()
    loop = make_loop(tmp_path, provider, gate)
    events = await collect(loop, turn("write"))

    assert gate.seen == []
    assert (tmp_path / "a.txt").read_text() == "alpha\n"
    result = next(m for m in loop.conversation if isinstance(m, ToolResultTurn))
    assert result.is_error
    assert "output limit" in result.content
    last = events[-1]
    assert isinstance(last, RunEnd)
    assert last.reason is RunEndReason.STOP


async def test_refusal_ends_run_without_tools(tmp_path: Path) -> None:
    refused = (
        ToolCallReady(call=ToolCallRequest(id="c1", name="bash", args={"command": "ls"})),
        Stop(reason="refusal"),
    )
    gate = StubGate()
    events = await collect(make_loop(tmp_path, FakeProvider([refused]), gate), turn("go"))
    assert gate.seen == []
    last = events[-1]
    assert isinstance(last, RunEnd)
    assert last.reason is RunEndReason.ERROR


async def test_malformed_arguments_are_reported(tmp_path: Path) -> None:
    broken = (
        ToolCallReady(call=ToolCallRequest(id="c1", name="read", parse_error="invalid JSON")),
        Stop(reason="tool_use"),
    )
    provider = FakeProvider([broken, reply("ok")])
    gate = StubGate()
    loop = make_loop(tmp_path, provider, gate)
    await collect(loop, turn("read"))
    assert gate.seen == []
    result = next(m for m in loop.conversation if isinstance(m, ToolResultTurn))
    assert result.is_error
    assert "invalid JSON" in result.content


async def test_provider_error_closes_message_and_run(tmp_path: Path) -> None:
    loop = AgentLoop(
        provider=FailingProvider(),
        tools=builtin_tools(),
        gate=StubGate(),
        context=ContextBuilder(),
        tool_ctx=ToolCtx(workspace=Workspace.at(tmp_path), backend=LocalBackend()),
        ids=UlidGenerator(),
    )
    events = await collect(loop, turn("hi"))
    assert isinstance(events[-2], MessageEnd)
    assert events[-2].text == "partial"
    last = events[-1]
    assert isinstance(last, RunEnd)
    assert last.reason is RunEndReason.ERROR
    assert last.error == "anthropic 529: overloaded"


async def test_native_content_is_replayed_and_history_is_append_only(tmp_path: Path) -> None:
    native = NativeContent(provider="anthropic", blocks=({"type": "thinking", "signature": "s"},))
    first = (*use_tool("read", path="a.txt"), NativeReady(content=native))
    long_output = "x" * 5000
    (tmp_path / "big.txt").write_text(long_output)
    calls = [
        use_tool("read", f"c{i}", path="big.txt") if i % 2 else use_tool("ls", f"c{i}", path=".")
        for i in range(10)
    ]
    provider = FakeProvider([first, *calls, reply("ok")])
    events = await collect(make_loop(tmp_path, provider, StubGate()), turn("read"))

    last = events[-1]
    assert isinstance(last, RunEnd)
    assert last.reason is RunEndReason.STOP

    replayed = provider.requests[1].messages[1]
    assert replayed.native == native
    for earlier, later in itertools.pairwise(provider.requests):
        assert later.messages[: len(earlier.messages)] == earlier.messages


async def test_silent_model_times_out_before_first_output(tmp_path: Path) -> None:
    class Mute:
        async def stream(
            self, request: LlmRequest, *, cancel: asyncio.Event
        ) -> AsyncIterator[LlmEvent]:
            await asyncio.sleep(3600)
            yield Stop()

    loop = make_loop(
        tmp_path, Mute(), StubGate(), LoopLimits(first_token_timeout_s=0.05, idle_timeout_s=5)
    )
    events = await collect(loop, turn("hi"))
    last = events[-1]
    assert isinstance(last, RunEnd)
    assert last.reason is RunEndReason.ERROR
    assert last.error == "model produced no output for 0.05s"


async def test_stalled_stream_times_out_between_events(tmp_path: Path) -> None:
    limits = LoopLimits(first_token_timeout_s=5, idle_timeout_s=0.05)
    loop = make_loop(tmp_path, StallingProvider(text="par"), StubGate(), limits)
    events = await collect(loop, turn("hi"))
    ended = next(e for e in events if isinstance(e, MessageEnd))
    last = events[-1]
    assert ended.text == "par"
    assert isinstance(last, RunEnd)
    assert last.reason is RunEndReason.ERROR
    assert last.error == "model produced no output for 0.05s"
    assert last.usage.output_tokens == 3


async def abort_after(loop: AgentLoop, delay: float) -> tuple[list[AgentEvent], float]:
    cancel = asyncio.Event()
    started = asyncio.get_running_loop().time()

    async def drain() -> list[AgentEvent]:
        return [event async for event in loop.run(turn("go"), cancel=cancel)]

    task = asyncio.create_task(drain())
    await asyncio.sleep(delay)
    cancel.set()
    events = await asyncio.wait_for(task, 2)
    return events, asyncio.get_running_loop().time() - started


async def test_abort_before_any_output_leaves_no_empty_assistant_turn(tmp_path: Path) -> None:
    loop = make_loop(tmp_path, StallingProvider(), StubGate(), LoopLimits())
    events, elapsed = await abort_after(loop, 0.05)
    last = events[-1]
    assert isinstance(last, RunEnd)
    assert last.reason is RunEndReason.ABORTED
    assert last.usage.input_tokens == 7
    assert elapsed < 1
    assert not any(isinstance(m, AssistantTurn) for m in loop.conversation)


async def test_abort_mid_stream_keeps_the_partial_answer(tmp_path: Path) -> None:
    loop = make_loop(tmp_path, StallingProvider(text="half an ans"), StubGate(), LoopLimits())
    events, _ = await abort_after(loop, 0.05)
    ended = next(e for e in events if isinstance(e, MessageEnd))
    assert ended.text == "half an ans"
    assert [m.text for m in loop.conversation if isinstance(m, AssistantTurn)] == ["half an ans"]


async def test_abort_while_waiting_for_approval(tmp_path: Path) -> None:
    provider = FakeProvider([use_tool("bash", command="make")])
    loop = make_loop(tmp_path, provider, StubGate(block=True))
    events, _ = await abort_after(loop, 0.1)
    result = next(e for e in events if isinstance(e, ToolEnd))
    assert result.result.content == "Not executed: run aborted"
    last = events[-1]
    assert isinstance(last, RunEnd)
    assert last.reason is RunEndReason.ABORTED
    assert isinstance(loop.conversation[-1], ToolResultTurn)


async def test_abort_kills_a_running_command(tmp_path: Path) -> None:
    provider = FakeProvider([use_tool("bash", command="sleep 30")])
    loop = make_loop(tmp_path, provider, StubGate())
    events, elapsed = await abort_after(loop, 0.5)
    assert any(isinstance(e, ToolStart) for e in events)
    last = events[-1]
    assert isinstance(last, RunEnd)
    assert last.reason is RunEndReason.ABORTED
    assert elapsed < 5


async def test_each_run_starts_a_fresh_gate_window(tmp_path: Path) -> None:
    gate = StubGate()
    loop = make_loop(tmp_path, FakeProvider([reply("a"), reply("b")]), gate)
    await collect(loop, turn("one"))
    await collect(loop, turn("two"))
    assert gate.runs == 2
