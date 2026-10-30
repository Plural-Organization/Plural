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
        "    json.dump({'argv': sys.argv[1:], 'prompt': sys.stdin.read(), "
        "'api_key': os.getenv('ANTHROPIC_API_KEY')}, target)\n"
        "answer = response.get('structured_output')\n"
        "if isinstance(answer, dict):\n"
        "    encoded = json.dumps(answer, ensure_ascii=False)\n"
        "    for offset in range(0, len(encoded), 7):\n"
        "        print(json.dumps({'type': 'stream_event', "
        "'event': {'type': 'content_block_delta', "
        "'delta': {'type': 'input_json_delta', 'partial_json': encoded[offset:offset + 7]}}}))\n"
        "print(json.dumps({'type': 'result', **response}))\n"
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
    text, label, image = line["message"]["content"]
    conversation = json.loads(text["text"].split("\n", 1)[1])
    assert conversation["messages"][0]["images"] == ["image 1"]
    assert "images" not in conversation["messages"][2]
    assert label == {"type": "text", "text": "[image 1]"}
    assert image["source"] == {"type": "base64", "media_type": "image/png", "data": "cmVk"}
