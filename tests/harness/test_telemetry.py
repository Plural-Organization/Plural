import asyncio
import importlib.util
import json
from collections.abc import AsyncIterator, MutableMapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from structlog.testing import capture_logs
from tests.doubles import FakeProvider, ScriptedProvider, reply, use_tool
from tests.loop_support import StubGate, collect, make_loop, turn

from plural.agent.context.context import ContextBuilder
from plural.agent.context.telemetry import RequestDump, hit_rate, observed
from plural.agent.loop.loop import AgentLoop, LoopLimits
from plural.agent.providers.base import (
    LlmEvent,
    LlmImage,
    LlmMessage,
    LlmRequest,
    ProviderError,
    Stop,
    TextDelta,
    UsageReport,
)
from plural.agent.sandbox.base import Workspace
from plural.agent.sandbox.local import LocalBackend
from plural.agent.tools.base import ToolCtx
from plural.agent.tools.registry import builtin_tools
from plural.host.system import UlidGenerator
from plural.protocol.models import ContextPartKind, Usage

REQUEST = LlmRequest(system="s", messages=(LlmMessage(role="user", content="hi"),))


async def _events(*events: LlmEvent) -> AsyncIterator[LlmEvent]:
    for event in events:
        await asyncio.sleep(0)
        yield event


async def _drain(events: AsyncIterator[LlmEvent]) -> None:
    async for _ in events:
        pass


def _logged(logs: Sequence[MutableMapping[str, Any]], event: str) -> list[MutableMapping[str, Any]]:
    return [line for line in logs if line["event"] == event]


def test_hit_rate_is_the_cached_share_of_the_prompt() -> None:
    assert hit_rate(Usage(input_tokens=10, cache_read_tokens=80, cache_write_tokens=10)) == 0.8
    assert hit_rate(Usage(output_tokens=5)) is None


async def test_a_model_call_logs_its_cost_and_timing() -> None:
    usage = Usage(input_tokens=100, cache_read_tokens=900, cache_write_tokens=0, output_tokens=7)
    with capture_logs() as logs:
        await _drain(
            observed(
                _events(TextDelta(text="hi"), UsageReport(usage=usage), Stop()),
                REQUEST,
                purpose="turn",
                role="main",
            )
        )
    [line] = _logged(logs, "llm.call")
    assert line["outcome"] == "ok"
    assert line["stop"] == "end_turn"
    assert (line["input"], line["cache_read"], line["output"]) == (100, 900, 7)
    assert line["hit"] == 0.9
    assert line["first_ms"] is not None
    assert line["messages"] == 1


async def test_a_failed_model_call_is_logged_as_an_error() -> None:
    async def failing() -> AsyncIterator[LlmEvent]:
        yield TextDelta(text="partial")
        raise ProviderError("boom")

    with capture_logs() as logs, pytest.raises(ProviderError):
        await _drain(observed(failing(), REQUEST, purpose="compact", role="fast"))
    [line] = _logged(logs, "llm.call")
    assert (line["outcome"], line["purpose"], line["role"]) == ("error", "compact", "fast")
    assert line["hit"] is None


def test_requests_are_numbered_on_from_an_earlier_host(tmp_path: Path) -> None:
    folder = tmp_path / "requests"
    image = LlmImage(media_type="image/png", data="A" * 40)
    request = LlmRequest(
        system="s", messages=(LlmMessage(role="user", content="look", images=(image,)),)
    )
    first = RequestDump(folder).write(request, "turn")
    second = RequestDump(folder).write(request, "compact")

    assert (first.name, second.name) == ("00001-turn.json", "00002-compact.json")
    saved = json.loads(first.read_text())
    assert saved["messages"][0]["images"][0]["data"] == "<40 base64 characters>"


def _loop(tmp_path: Path, provider: FakeProvider, dump: RequestDump | None) -> AgentLoop:
    (tmp_path / "a.txt").write_text("alpha\n")
    return AgentLoop(
        provider=provider,
        tools=builtin_tools(),
        gate=StubGate(),
        context=ContextBuilder(),
        tool_ctx=ToolCtx(workspace=Workspace.at(tmp_path), backend=LocalBackend()),
        ids=UlidGenerator(),
        dump=dump,
    )


async def test_a_run_logs_each_model_call_and_tool_call(tmp_path: Path) -> None:
    provider = FakeProvider([use_tool("read", "c1", path="a.txt"), reply("done")])
    loop = _loop(tmp_path, provider, RequestDump(tmp_path / "requests"))
    with capture_logs() as logs:
        await collect(loop, turn("go"))

    calls = _logged(logs, "llm.call")
    assert [(line["purpose"], line["role"]) for line in calls] == [("turn", "main")] * 2
    assert [Path(line["request"]).name for line in calls] == ["00001-turn.json", "00002-turn.json"]
    [tool] = _logged(logs, "tool.call")
    assert (tool["tool"], tool["allowed"], tool["error"]) == ("read", True, False)
    assert tool["run_ms"] is not None


async def test_a_denied_tool_call_is_logged_without_running(tmp_path: Path) -> None:
    provider = FakeProvider([use_tool("read", "c1", path="a.txt"), reply("done")])
    loop = make_loop(tmp_path, provider, StubGate(allowed=False))
    with capture_logs() as logs:
        await collect(loop, turn("go"))
    [tool] = _logged(logs, "tool.call")
    assert (tool["allowed"], tool["error"], tool["run_ms"]) == (False, True, None)


async def test_compaction_logs_why_and_how_much_it_saved(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        [
            (UsageReport(usage=Usage(input_tokens=900)), *use_tool("ls", "c1", path=".")),
            reply("<summary>listed the workspace</summary>"),
            reply("finished"),
        ]
    )
    limits = LoopLimits(context_window=1000, compact_reserve=500)
    with capture_logs() as logs:
        await collect(make_loop(tmp_path, provider, StubGate(), limits), turn("go"))

    [line] = _logged(logs, "context.compacted")
    assert (line["reason"], line["role"]) == ("threshold", "main")
    assert line["tokens_before"] > 900
    assert line["tokens_after"] < 900
    assert [call["purpose"] for call in _logged(logs, "llm.call")] == ["turn", "compact", "turn"]


def _prefix_diff() -> ModuleType:
    path = Path(__file__).parents[2] / "scripts" / "prefix_diff.py"
    spec = importlib.util.spec_from_file_location("prefix_diff", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prefix_diff_names_what_broke_the_shared_beginning() -> None:
    compare = _prefix_diff().compare
    tool: dict[str, Any] = {"name": "read", "description": "", "parameters": {}}
    base: dict[str, Any] = {
        "system": "you are",
        "tools": [tool],
        "messages": [{"role": "user", "content": "a"}],
    }
    longer: dict[str, Any] = {
        **base,
        "messages": [*base["messages"], {"role": "assistant", "content": "b"}],
    }

    assert compare(base, longer) == "extends the previous request (+1 messages)"
    changed = compare(base, {**longer, "system": "you were"})
    assert changed.startswith("system changed at character 4")
    assert compare(base, {**base, "tools": []}) == "tools changed: ['read'] -> []"
    edited: dict[str, Any] = {
        **longer,
        "messages": [{"role": "user", "content": "A"}, longer["messages"][1]],
    }
    assert compare(longer, edited).startswith("message 0 (user) changed at character 0")


async def test_the_context_is_broken_down_and_scaled_to_the_provider_count(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.txt").write_text("alpha\n" * 400)
    usage = Usage(input_tokens=1000, cache_read_tokens=3000)
    provider = ScriptedProvider(
        [
            (UsageReport(usage=usage), *use_tool("read", "c1", path="a.txt")),
            (UsageReport(usage=usage), *reply("done")),
        ]
    )
    loop = make_loop(tmp_path, provider, StubGate())
    await collect(loop, turn("go"))

    fill = loop.fill()
    kinds = {(part.kind, part.name) for part in fill.parts}
    assert {
        (ContextPartKind.SYSTEM, None),
        (ContextPartKind.TOOLS, None),
        (ContextPartKind.MESSAGES, None),
        (ContextPartKind.TOOL_RESULTS, "read"),
    } <= kinds
    assert abs(sum(part.tokens for part in fill.parts) - fill.tokens) <= len(fill.parts)
    assert fill.hit == 0.75


async def test_the_context_is_the_last_request_when_usage_sums_several(tmp_path: Path) -> None:
    summed = Usage(input_tokens=4, cache_write_tokens=1977, cache_read_tokens=1849)
    last = Usage(input_tokens=2, cache_write_tokens=128, cache_read_tokens=1849)
    provider = ScriptedProvider([(UsageReport(usage=summed, last=last), *reply("done"))])
    loop = make_loop(tmp_path, provider, StubGate())
    await collect(loop, turn("go"))

    fill = loop.fill()
    assert 1979 <= fill.tokens < 2000
    assert fill.hit == 0.934
    assert loop.usage == summed
