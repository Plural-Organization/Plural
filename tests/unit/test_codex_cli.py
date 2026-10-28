import asyncio
import sys
from pathlib import Path

import pytest
from tests.loop_support import StubGate, collect, make_loop, turn

from plural.agent.events import MessageEnd, RunEnd
from plural.agent.loop import LoopLimits
from plural.agent.providers import codex_cli
from plural.agent.providers.codex_cli import CodexCliProvider
from plural.protocol.models import RunEndReason


def fake_codex(tmp_path: Path, *, progress: str) -> Path:
    cli = tmp_path / "codex"
    cli.write_text(
        f"#!{sys.executable}\n"
        "import json, sys, time\n"
        "if sys.argv[1:3] == ['login', 'status'] or '--help' in sys.argv:\n"
        "    sys.exit(0)\n"
        "def emit(method, params):\n"
        "    print(json.dumps({'method': method, 'params': params}), flush=True)\n"
        f"progress = {progress!r}\n"
        "for line in sys.stdin:\n"
        "    msg = json.loads(line)\n"
        "    if 'id' not in msg: continue\n"
        "    method = msg['method']\n"
        "    if progress == 'rpc_silent' and method == 'thread/start': continue\n"
        "    result = {'thread': {'id': 'thread_test'}} if method == 'thread/start' else {}\n"
        "    print(json.dumps({'id': msg['id'], 'result': result}), flush=True)\n"
        "    if method != 'turn/start': continue\n"
        "    if progress == 'initial':\n"
        "        emit('item/started', {'item': {'type': 'reasoning'}})\n"
        "        time.sleep(0.25)\n"
        "    emit('item/agentMessage/delta', {'delta': '{\"text\":\"Working\"'})\n"
        "    for _ in range(6):\n"
        "        time.sleep(0.12 if progress == 'long_silent' else 0.04)\n"
        "        if progress in {'reasoning', 'initial'}:\n"
        "            emit('item/reasoning/summaryTextDelta', {'delta': 'Still working.'})\n"
        "        elif progress == 'raw_reasoning':\n"
        "            emit('item/reasoning/textDelta', {'delta': 'Still working.'})\n"
        "        elif progress == 'structured':\n"
        "            emit('item/agentMessage/delta', {'delta': ' '})\n"
        "    emit('turn/completed', {'turn': {'status': 'completed', 'items': [\n"
        "        {'type': 'agentMessage', 'text': json.dumps(\n"
        "            {'text': 'Working', 'tool_calls': []})}\n"
        "    ]}})\n"
    )
    cli.chmod(0o755)
    return cli


async def run_codex(
    tmp_path: Path, progress: str, *, idle_timeout_s: float = 0.15
) -> list[RunEnd | MessageEnd]:
    cli = fake_codex(tmp_path, progress=progress)
    provider = CodexCliProvider(workspace=tmp_path, cli=str(cli))
    loop = make_loop(
        tmp_path,
        provider,
        StubGate(),
        LoopLimits(first_token_timeout_s=2, idle_timeout_s=idle_timeout_s),
    )
    try:
        events = await asyncio.wait_for(collect(loop, turn("hello")), 5)
    finally:
        await provider.close()
    return [event for event in events if isinstance(event, RunEnd | MessageEnd)]


@pytest.mark.parametrize("progress", ["reasoning", "raw_reasoning", "initial"])
async def test_codex_reasoning_activity_keeps_the_run_alive(tmp_path: Path, progress: str) -> None:
    events = await run_codex(tmp_path, progress)
    assert isinstance(events[-1], RunEnd)
    assert events[-1].reason is RunEndReason.STOP


async def test_codex_structured_output_activity_keeps_the_run_alive(tmp_path: Path) -> None:
    events = await run_codex(tmp_path, "structured")
    assert isinstance(events[-1], RunEnd)
    assert events[-1].reason is RunEndReason.STOP
    assert any(isinstance(event, MessageEnd) and event.text == "Working" for event in events)


async def test_codex_still_times_out_when_the_server_stops_producing_events(tmp_path: Path) -> None:
    events = await run_codex(tmp_path, "silent")
    assert isinstance(events[-1], RunEnd)
    assert events[-1].reason is RunEndReason.ERROR
    assert events[-1].error == "model produced no output for 0.15s"


async def test_codex_generation_uses_the_loop_deadline_instead_of_the_rpc_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(codex_cli, "RPC_TIMEOUT_S", 0.5)
    events = await run_codex(tmp_path, "long_silent", idle_timeout_s=1.5)
    assert isinstance(events[-1], RunEnd)
    assert events[-1].reason is RunEndReason.STOP


async def test_codex_rpc_still_has_a_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(codex_cli, "RPC_TIMEOUT_S", 0.5)
    events = await run_codex(tmp_path, "rpc_silent")
    assert isinstance(events[-1], RunEnd)
    assert events[-1].reason is RunEndReason.ERROR
    assert events[-1].error == "Codex app server timed out waiting for thread/start"
