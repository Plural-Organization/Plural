import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

from plural.agent.providers.base import (
    LlmImage,
    LlmMessage,
    LlmRequest,
    ProviderActivity,
    ProviderError,
    Stop,
    TextDelta,
    ToolCallReady,
    ToolSchema,
    UsageReport,
)
from plural.agent.providers.cli.claude_code import ClaudeCodeProvider


def fake_cli(tmp_path: Path, response: dict[str, object], *, exit_code: int = 0) -> Path:
    script = tmp_path / "claude"
    record = tmp_path / "request.json"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        f"response = json.loads({json.dumps(response)!r})\n"
        f"with open({str(record)!r}, 'w') as target:\n"
        "    json.dump({'argv': sys.argv[1:], 'prompt': sys.stdin.readline(), "
        "'api_key': os.getenv('ANTHROPIC_API_KEY')}, target)\n"
        "answer = response.get('structured_output')\n"
        "if isinstance(answer, dict):\n"
        "    encoded = json.dumps(answer, ensure_ascii=False)\n"
        "    for offset in range(0, len(encoded), 7):\n"
        "        print(json.dumps({'type': 'stream_event', "
        "'event': {'type': 'content_block_delta', "
        "'delta': {'type': 'input_json_delta', 'partial_json': encoded[offset:offset + 7]}}}))\n"
        "print(json.dumps({'type': 'result', **response}), flush=True)\n"
        f"sys.exit({exit_code})\n"
    )
    script.chmod(0o755)
    return script


async def test_claude_code_cli_uses_selected_model_and_returns_plural_tool_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-reach-claude-code")
    cli = fake_cli(
        tmp_path,
        {
            "structured_output": {
                "text": "I will read it.",
                "tool_calls": [{"name": "read", "args": {"path": "a.txt"}}],
            },
            "usage": {"input_tokens": 12, "output_tokens": 7},
        },
    )
    provider = ClaudeCodeProvider(model="claude-sonnet-5-5", workspace=tmp_path, cli=str(cli))
    request = LlmRequest(
        system="Be careful.",
        messages=(LlmMessage(role="user", content="Read a.txt"),),
        tools=(ToolSchema(name="read", description="Read file", parameters={"type": "object"}),),
    )
    events = [event async for event in provider.stream(request, cancel=asyncio.Event())]
    text = "".join(event.text for event in events if isinstance(event, TextDelta))
    assert text == "I will read it."
    calls = [event for event in events if isinstance(event, ToolCallReady)]
    assert len(calls) == 1
    assert calls[0].call.name == "read"
    assert calls[0].call.args == {"path": "a.txt"}
    assert events[-1] == Stop(reason="tool_use")
    sent = json.loads((tmp_path / "request.json").read_text())
    assert sent["argv"][sent["argv"].index("--model") + 1] == "claude-sonnet-5-5"
    assert sent["argv"][sent["argv"].index("--tools") + 1] == ""
    assert "--safe-mode" in sent["argv"]
    assert sent["argv"][sent["argv"].index("--output-format") + 1] == "stream-json"
    assert "--include-partial-messages" in sent["argv"]
    schema = json.loads(sent["argv"][sent["argv"].index("--json-schema") + 1])
    assert schema["required"] == ["text", "tool_calls"]
    assert "Read a.txt" in sent["prompt"]
    assert sent["api_key"] is None


async def test_claude_code_cli_names_missing_login(tmp_path: Path) -> None:
    cli = fake_cli(tmp_path, {"is_error": True, "result": "Not logged in"}, exit_code=1)
    provider = ClaudeCodeProvider(workspace=tmp_path, cli=str(cli))
    request = LlmRequest(system="Be careful.", messages=(LlmMessage(role="user", content="Hi"),))
    with pytest.raises(ProviderError, match="Not logged in"):
        [event async for event in provider.stream(request, cancel=asyncio.Event())]


async def test_cancelling_a_run_stops_waiting_for_claude_code(tmp_path: Path) -> None:
    cli = tmp_path / "claude"
    cli.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(10)\n")
    cli.chmod(0o755)
    provider = ClaudeCodeProvider(workspace=tmp_path, cli=str(cli))
    request = LlmRequest(system="Be careful.", messages=(LlmMessage(role="user", content="Hi"),))
    cancel = asyncio.Event()

    async def run() -> None:
        [event async for event in provider.stream(request, cancel=cancel)]

    started = time.monotonic()
    task = asyncio.create_task(run())
    await asyncio.sleep(0.1)
    cancel.set()
    await asyncio.wait_for(task, 2)
    assert time.monotonic() - started < 2


async def test_a_long_tool_call_from_claude_code_counts_as_activity(tmp_path: Path) -> None:
    content = "x = 1\n" * 400
    cli = fake_cli(
        tmp_path,
        {
            "structured_output": {
                "text": "Writing it.",
                "tool_calls": [{"name": "write", "args": {"path": "big.py", "content": content}}],
            },
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    )
    provider = ClaudeCodeProvider(workspace=tmp_path, cli=str(cli))
    request = LlmRequest(
        system="s",
        messages=(LlmMessage(role="user", content="write"),),
        tools=(ToolSchema(name="write", description="Write", parameters={"type": "object"}),),
    )
    events = [event async for event in provider.stream(request, cancel=asyncio.Event())]
    text = "".join(event.text for event in events if isinstance(event, TextDelta))
    activity = [event for event in events if isinstance(event, ProviderActivity)]
    assert text == "Writing it."
    assert len(activity) > 100
    assert {event.source for event in activity} == {"input_json_delta"}


async def test_claude_code_receives_the_conversation_images(tmp_path: Path) -> None:
    cli = fake_cli(tmp_path, {"structured_output": {"text": "red", "tool_calls": []}})
    provider = ClaudeCodeProvider(model="claude-sonnet-5-5", workspace=tmp_path, cli=str(cli))
    red = LlmImage(media_type="image/png", data="cmVk")
    request = LlmRequest(
        system="",
        messages=(
            LlmMessage(role="user", content="what color?", images=(red,)),
            LlmMessage(role="assistant", content="red"),
            LlmMessage(role="user", content="and now?"),
        ),
    )
    [event async for event in provider.stream(request, cancel=asyncio.Event())]
    sent = json.loads((tmp_path / "request.json").read_text())
    assert sent["argv"][sent["argv"].index("--input-format") + 1] == "stream-json"
    line = json.loads(sent["prompt"])
    assert line["type"] == "user"
    _, _, asked, label, image, answered, followed = line["message"]["content"]
    assert json.loads(asked["text"])["message"]["images"] == ["image 1"]
    assert label == {"type": "text", "text": "[image 1]"}
    assert image["source"] == {"type": "base64", "media_type": "image/png", "data": "cmVk"}
    assert json.loads(answered["text"])["message"]["content"] == "red"
    assert "images" not in json.loads(followed["text"])["message"]


def lasting_cli(tmp_path: Path) -> Path:
    """A Claude Code that keeps answering on one process, as `--input-format stream-json` does,
    and records each message it was sent and each time it started."""
    script = tmp_path / "claude"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        f"open({str(tmp_path / 'starts')!r}, 'a').write('x')\n"
        "for line in sys.stdin:\n"
        f"    open({str(tmp_path / 'sent.jsonl')!r}, 'a').write(line)\n"
        "    answer = {'text': 'ok', 'tool_calls': []}\n"
        "    print(json.dumps({'type': 'result', 'structured_output': answer, "
        "'usage': {'input_tokens': 3, 'cache_read_input_tokens': 100}}), flush=True)\n"
    )
    script.chmod(0o755)
    return script


async def test_a_conversation_keeps_one_process_and_sends_only_what_is_new(tmp_path: Path) -> None:
    provider = ClaudeCodeProvider(workspace=tmp_path, cli=str(lasting_cli(tmp_path)))
    tools = (ToolSchema(name="read", description="Read file", parameters={"type": "object"}),)
    first = (LlmMessage(role="user", content="hello"),)
    second = (
        *first,
        LlmMessage(role="assistant", content="ok"),
        LlmMessage(role="user", content="again"),
    )
    try:
        for messages in (first, second):
            request = LlmRequest(system="s", messages=messages, tools=tools)
            events = [event async for event in provider.stream(request, cancel=asyncio.Event())]
            assert events[-1] == Stop(reason="end_turn")
    finally:
        await provider.close()
    assert (tmp_path / "starts").read_text() == "x"
    sent = [
        json.loads(line)["message"]["content"]
        for line in (tmp_path / "sent.jsonl").read_text().splitlines()
    ]
    assert '"read"' in str(sent[0][1]["text"])
    assert "hello" in str(sent[0])
    # The model's own answer is in Claude Code's history; only the new message goes.
    assert len(sent[1]) == 1
    assert "again" in sent[1][0]["text"]
    assert "hello" not in str(sent[1])


async def test_another_conversation_or_a_changed_history_starts_over(tmp_path: Path) -> None:
    provider = ClaudeCodeProvider(workspace=tmp_path, cli=str(lasting_cli(tmp_path)))
    hello = (LlmMessage(role="user", content="hello"),)
    try:
        for system, messages in (
            ("s", hello),
            ("summarize", hello),
            (
                "s",
                (
                    *hello,
                    LlmMessage(role="assistant", content="ok"),
                    LlmMessage(role="user", content="more"),
                ),
            ),
            (
                "s",
                (
                    LlmMessage(role="user", content="hello"),
                    LlmMessage(role="user", content="summary instead"),
                ),
            ),
        ):
            request = LlmRequest(system=system, messages=messages)
            [event async for event in provider.stream(request, cancel=asyncio.Event())]
    finally:
        await provider.close()
    # The summary has a process of its own; the main one goes on; a rewritten history restarts.
    assert (tmp_path / "starts").read_text() == "xxx"


async def test_a_process_that_ended_is_started_again_with_everything(tmp_path: Path) -> None:
    # This Claude Code answers once and exits, as one that crashed between turns would.
    cli = fake_cli(tmp_path, {"structured_output": {"text": "ok", "tool_calls": []}})
    provider = ClaudeCodeProvider(workspace=tmp_path, cli=str(cli))
    first = (LlmMessage(role="user", content="hello"),)
    second = (
        *first,
        LlmMessage(role="assistant", content="ok"),
        LlmMessage(role="user", content="again"),
    )
    for messages in (first, second):
        request = LlmRequest(system="s", messages=messages)
        events = [event async for event in provider.stream(request, cancel=asyncio.Event())]
        assert events[-1] == Stop(reason="end_turn")
    prompt = json.loads((tmp_path / "request.json").read_text())["prompt"]
    assert "hello" in prompt
    assert "again" in prompt


async def test_claude_code_reports_the_window_of_its_model(tmp_path: Path) -> None:
    cli = fake_cli(
        tmp_path,
        {
            "structured_output": {"text": "ok", "tool_calls": []},
            "modelUsage": {"claude-sonnet-5-5": {"contextWindow": 1_000_000}},
        },
    )
    provider = ClaudeCodeProvider(workspace=tmp_path, cli=str(cli))
    assert await provider.context_window() is None
    request = LlmRequest(system="", messages=(LlmMessage(role="user", content="hi"),))
    [event async for event in provider.stream(request, cancel=asyncio.Event())]
    assert await provider.context_window() == 1_000_000


async def test_text_written_beside_the_structured_answer_is_not_shown_twice(
    tmp_path: Path,
) -> None:
    script = tmp_path / "claude"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        "sys.stdin.readline()\n"
        "def delta(d): print(json.dumps({'type': 'stream_event', "
        "'event': {'type': 'content_block_delta', 'delta': d}}))\n"
        "delta({'type': 'text_delta', 'text': 'The answer.'})\n"
        "delta({'type': 'input_json_delta', 'partial_json': json.dumps("
        "{'text': 'The answer.', 'tool_calls': []})})\n"
        "print(json.dumps({'type': 'result', 'structured_output': "
        "{'text': 'The answer.', 'tool_calls': []}}))\n"
    )
    script.chmod(0o755)
    provider = ClaudeCodeProvider(workspace=tmp_path, cli=str(script))
    request = LlmRequest(system="", messages=(LlmMessage(role="user", content="hi"),))
    events = [event async for event in provider.stream(request, cancel=asyncio.Event())]
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "The answer."


def scripted_cli(tmp_path: Path, lines: list[dict[str, object]], *, then_sleep: float = 0) -> Path:
    """A Claude Code that prints these stream-json lines, then waits before it exits."""
    script = tmp_path / "claude"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, sys, time\n"
        "sys.stdin.readline()\n"
        f"for line in json.loads({json.dumps(lines)!r}):\n"
        "    print(json.dumps(line), flush=True)\n"
        f"time.sleep({then_sleep})\n"
    )
    script.chmod(0o755)
    return script


TOOLS = (
    ToolSchema(name="bash", description="Run a command", parameters={"type": "object"}),
    ToolSchema(name="ls", description="List a folder", parameters={"type": "object"}),
)


async def test_a_plural_tool_called_as_claude_codes_own_still_runs(tmp_path: Path) -> None:
    usage = {"input_tokens": 3, "cache_read_input_tokens": 900, "output_tokens": 20}
    cli = scripted_cli(
        tmp_path,
        [
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_start",
                    "content_block": {"type": "tool_use", "name": "bash"},
                },
            },
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "input_json_delta", "partial_json": '{"text": "no"}'},
                },
            },
            {
                "type": "assistant",
                "message": {
                    "id": "msg_1",
                    "content": [
                        {"type": "text", "text": "Listing it."},
                        {"type": "tool_use", "name": "bash", "input": {"command": "ls -la"}},
                    ],
                    "usage": usage,
                },
            },
        ],
        # Claude Code would answer "No such tool available" and go on.
        then_sleep=30,
    )
    provider = ClaudeCodeProvider(workspace=tmp_path, cli=str(cli))
    request = LlmRequest(
        system="", messages=(LlmMessage(role="user", content="List it"),), tools=TOOLS
    )
    started = time.monotonic()
    events = [event async for event in provider.stream(request, cancel=asyncio.Event())]
    assert time.monotonic() - started < 10
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "Listing it."
    calls = [e.call for e in events if isinstance(e, ToolCallReady)]
    assert [(call.name, call.args) for call in calls] == [("bash", {"command": "ls -la"})]
    report = next(e for e in events if isinstance(e, UsageReport))
    assert report.usage.prompt_tokens == 903
    assert events[-1] == Stop(reason="tool_use")


async def test_the_context_is_the_last_request_of_the_answer(tmp_path: Path) -> None:
    first = {"input_tokens": 2, "cache_creation_input_tokens": 1849, "output_tokens": 30}
    last = {
        "input_tokens": 2,
        "cache_creation_input_tokens": 128,
        "cache_read_input_tokens": 1849,
        "output_tokens": 40,
    }
    cli = fake_cli(
        tmp_path,
        {
            "structured_output": {"text": "Done.", "tool_calls": []},
            "usage": {
                "input_tokens": 4,
                "cache_creation_input_tokens": 1977,
                "cache_read_input_tokens": 1849,
                "output_tokens": 70,
                "iterations": [first, last],
            },
        },
    )
    provider = ClaudeCodeProvider(workspace=tmp_path, cli=str(cli))
    request = LlmRequest(system="", messages=(LlmMessage(role="user", content="Hi"),))
    events = [event async for event in provider.stream(request, cancel=asyncio.Event())]
    report = next(e for e in events if isinstance(e, UsageReport))
    assert report.usage.prompt_tokens == 3830
    assert report.last is not None
    assert report.last.prompt_tokens == 1979
