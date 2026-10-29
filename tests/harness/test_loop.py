import asyncio
import itertools
from collections.abc import AsyncIterator, Mapping
from pathlib import Path

import pytest
from pydantic import JsonValue
from tests.doubles import ScriptedProvider, StallingProvider
from tests.loop_support import StubGate, collect, make_loop, turn

from plural.agent.context import ContextBuilder
from plural.agent.events import AgentEvent, MessageEnd, RunEnd, ToolEnd, ToolStart
from plural.agent.gate import GateResult
from plural.agent.loop import AgentLoop, LoopLimits
from plural.agent.messages import AssistantTurn, ToolResultTurn, attribute
from plural.agent.providers.base import (
    LlmEvent,
    LlmImage,
    LlmRequest,
    NativeContent,
    NativeReady,
    ProviderActivity,
    ProviderBusy,
    ProviderError,
    Stop,
    TextDelta,
    ToolCallReady,
    ToolCallRequest,
    ToolSchema,
)
from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.agent.sandbox.base import Workspace
from plural.agent.sandbox.local import LocalBackend
from plural.agent.tools.base import PreparedCall, Tool, ToolCtx, ToolResult
from plural.agent.tools.registry import ToolRegistry, builtin_tools
from plural.host.system import UlidGenerator
from plural.protocol.models import (
    Provenance,
    Role,
    RunEndReason,
    ToolCallView,
    ToolRisk,
)


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


async def test_a_long_tool_call_keeps_the_run_alive(tmp_path: Path) -> None:
    class Writing:
        """Streams a tool call for longer than the idle timeout, the way a long file arrives."""

        async def stream(
            self, request: LlmRequest, *, cancel: asyncio.Event
        ) -> AsyncIterator[LlmEvent]:
            if len(request.messages) > 1:
                yield TextDelta(text="written")
                yield Stop()
                return
            for _ in range(8):
                await asyncio.sleep(0.03)
                yield ProviderActivity(source="tool_call")
            call = ToolCallRequest(id="w1", name="write", args={"path": "big.py", "content": "x"})
            yield ToolCallReady(call=call)
            yield Stop(reason="tool_use")

    limits = LoopLimits(first_token_timeout_s=0.1, idle_timeout_s=0.1)
    events = await collect(make_loop(tmp_path, Writing(), StubGate(), limits), turn("write it"))
    last = events[-1]
    assert isinstance(last, RunEnd)
    assert last.reason is RunEndReason.STOP
    assert (tmp_path / "big.py").read_text() == "x"


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


class CountingGate(StubGate):
    def __init__(self) -> None:
        super().__init__()
        self.active = 0
        self.peak = 0

    async def check(
        self, call: ToolCallView, *, subject: str, provenance: Provenance
    ) -> GateResult:
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0.05)
        self.active -= 1
        return await super().check(call, subject=subject, provenance=provenance)


async def test_reads_in_one_turn_run_together_and_answer_in_order(tmp_path: Path) -> None:
    calls = (
        ToolCallRequest(id="c1", name="read", args={"path": "a.txt"}),
        ToolCallRequest(id="c2", name="ls", args={"path": "."}),
        ToolCallRequest(id="c3", name="bash", args={"command": "echo hi"}),
        ToolCallRequest(id="c4", name="read", args={"path": "a.txt"}),
    )
    turn_events: tuple[LlmEvent, ...] = (
        *(ToolCallReady(call=call) for call in calls),
        Stop(reason="tool_use"),
    )
    provider = FakeProvider([turn_events, reply("done")])
    gate = CountingGate()
    loop = make_loop(tmp_path, provider, gate)
    events = await collect(loop, turn("look"))

    assert gate.peak == 2
    assert [e.call.id for e in events if isinstance(e, ToolStart)][2:] == ["c3", "c4"]
    answered = [m.call_id for m in loop.conversation if isinstance(m, ToolResultTurn)]
    assert answered == ["c1", "c2", "c3", "c4"]
    assert all(not m.is_error for m in loop.conversation if isinstance(m, ToolResultTurn))


async def test_a_busy_provider_is_retried_before_any_output(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        [ProviderBusy("anthropic 529: overloaded"), ProviderBusy("anthropic 429"), reply("ok")]
    )
    limits = LoopLimits(retry_delay_s=0.01)
    events = await collect(make_loop(tmp_path, provider, StubGate(), limits), turn("hi"))
    last = events[-1]
    assert isinstance(last, RunEnd)
    assert last.reason is RunEndReason.STOP
    assert len(provider.requests) == 3


async def test_retries_give_up_with_the_last_error(tmp_path: Path) -> None:
    provider = ScriptedProvider([ProviderBusy("anthropic 529: overloaded")] * 3)
    limits = LoopLimits(retries=2, retry_delay_s=0.01)
    events = await collect(make_loop(tmp_path, provider, StubGate(), limits), turn("hi"))
    last = events[-1]
    assert isinstance(last, RunEnd)
    assert last.reason is RunEndReason.ERROR
    assert last.error == "anthropic 529: overloaded"
    assert len(provider.requests) == 3


class BusyMidStream:
    def __init__(self) -> None:
        self.requests = 0

    async def stream(
        self, request: LlmRequest, *, cancel: asyncio.Event
    ) -> AsyncIterator[LlmEvent]:
        self.requests += 1
        yield TextDelta(text="partial")
        raise ProviderBusy("anthropic 529: overloaded")


async def test_a_reply_that_already_started_is_not_retried(tmp_path: Path) -> None:
    provider = BusyMidStream()
    limits = LoopLimits(retry_delay_s=0.01)
    events = await collect(make_loop(tmp_path, provider, StubGate(), limits), turn("hi"))
    last = events[-1]
    assert isinstance(last, RunEnd)
    assert last.reason is RunEndReason.ERROR
    assert provider.requests == 1


async def test_an_image_the_model_rejects_is_dropped_so_the_next_run_works(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        [ProviderError("anthropic 400: Could not process image"), [TextDelta(text="ok")]]
    )
    loop = make_loop(tmp_path, provider, StubGate())
    image = LlmImage(media_type="image/png", data="aW1n")
    first = await collect(loop, turn("look").model_copy(update={"images": (image,)}))

    end = first[-1]
    assert isinstance(end, RunEnd)
    assert end.reason is RunEndReason.ERROR
    assert "images were removed" in (end.error or "")
    await collect(loop, turn("and now?"))
    assert all(not message.images for message in provider.requests[1].messages)
    assert "image(s) removed" in provider.requests[1].messages[0].content


class Handoff:
    name = "handoff"

    def schema(self) -> ToolSchema:
        return ToolSchema(name=self.name, description="Hand the turn back.", parameters={})

    def prepare(self, raw: Mapping[str, JsonValue]) -> PreparedCall:
        return PreparedCall(name=self.name, risk=ToolRisk.READ, subject="", execute=self._run)

    async def _run(self, ctx: ToolCtx) -> ToolResult:
        return ToolResult("handed back", terminate=True)


class Plugins:
    def __init__(self) -> None:
        self.items: list[Tool] = []

    def tools(self) -> list[Tool]:
        return self.items


class Install:
    name = "install"

    def __init__(self, plugins: Plugins) -> None:
        self._plugins = plugins

    def schema(self) -> ToolSchema:
        return ToolSchema(name=self.name, description="Install a plugin.", parameters={})

    def prepare(self, raw: Mapping[str, JsonValue]) -> PreparedCall:
        return PreparedCall(name=self.name, risk=ToolRisk.READ, subject="", execute=self._run)

    async def _run(self, ctx: ToolCtx) -> ToolResult:
        self._plugins.items.append(Handoff())
        return ToolResult("installed")


def loop_with(tmp_path: Path, provider: FakeProvider, tools: ToolRegistry) -> AgentLoop:
    return AgentLoop(
        provider=provider,
        tools=tools,
        gate=StubGate(),
        context=ContextBuilder(),
        tool_ctx=ToolCtx(workspace=Workspace.at(tmp_path), backend=LocalBackend()),
        ids=UlidGenerator(),
    )


async def test_turn_limit_ends_the_run_before_the_next_model_call(tmp_path: Path) -> None:
    provider = FakeProvider([use_tool("ls", path="."), reply("never asked")])
    loop = make_loop(tmp_path, provider, StubGate(limit="budget used up"))
    loop.steer(turn("and then this"))
    events = await collect(loop, turn("go", guest=True))
    last = events[-1]
    assert isinstance(last, RunEnd)
    assert (last.reason, last.error) == (RunEndReason.LIMIT, "budget used up")
    assert len(provider.requests) == 1
    assert [pending.text for pending in loop.drain_pending()] == ["and then this"]


async def test_turn_limit_does_not_cut_a_finished_answer(tmp_path: Path) -> None:
    provider = FakeProvider([reply("done")])
    events = await collect(make_loop(tmp_path, provider, StubGate(limit="budget")), turn("hi"))
    last = events[-1]
    assert isinstance(last, RunEnd)
    assert last.reason is RunEndReason.STOP


async def test_terminating_tools_hand_the_turn_back(tmp_path: Path) -> None:
    provider = FakeProvider([use_tool("handoff"), reply("never asked")])
    tools = ToolRegistry()
    tools.register(Handoff())
    events = await collect(loop_with(tmp_path, provider, tools), turn("go"))
    last = events[-1]
    assert isinstance(last, RunEnd)
    assert last.reason is RunEndReason.STOP
    assert len(provider.requests) == 1


async def test_a_terminating_tool_beside_a_normal_one_does_not_stop(tmp_path: Path) -> None:
    calls = (
        ToolCallReady(call=ToolCallRequest(id="c1", name="handoff", args={})),
        ToolCallReady(call=ToolCallRequest(id="c2", name="ls", args={"path": "."})),
        Stop(reason="tool_use"),
    )
    provider = FakeProvider([calls, reply("done")])
    tools = builtin_tools()
    tools.register(Handoff())
    await collect(loop_with(tmp_path, provider, tools), turn("go"))
    assert len(provider.requests) == 2


async def test_a_run_keeps_its_tool_list(tmp_path: Path) -> None:
    provider = FakeProvider([use_tool("install"), reply("done"), reply("again")])
    plugins = Plugins()
    tools = ToolRegistry()
    tools.register(Install(plugins))
    tools.add_source(plugins)
    loop = loop_with(tmp_path, provider, tools)
    await collect(loop, turn("install"))
    await collect(loop, turn("next"))
    names = [[schema.name for schema in request.tools] for request in provider.requests]
    assert names == [["install"], ["install"], ["install", "handoff"]]
