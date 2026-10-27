import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

from plural.agent.providers.base import (
    LlmMessage,
    LlmRequest,
    ProviderError,
    Stop,
    TextDelta,
    ToolCallReady,
    ToolSchema,
)
from plural.agent.providers.claude_code import ClaudeCodeProvider


def fake_cli(tmp_path: Path, response: dict[str, object], *, exit_code: int = 0) -> Path:
    script = tmp_path / "claude"
    record = tmp_path / "request.json"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        f"with open({str(record)!r}, 'w') as target:\n"
        "    json.dump({'argv': sys.argv[1:], 'prompt': sys.stdin.read(), "
        "'api_key': os.getenv('ANTHROPIC_API_KEY')}, target)\n"
        f"print({json.dumps(json.dumps(response))})\n"
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
    assert events[0] == TextDelta(text="I will read it.")
    assert isinstance(events[1], ToolCallReady)
    assert events[1].call.name == "read"
    assert events[1].call.args == {"path": "a.txt"}
    assert events[-1] == Stop(reason="tool_use")
    sent = json.loads((tmp_path / "request.json").read_text())
    assert sent["argv"][sent["argv"].index("--model") + 1] == "claude-sonnet-5-5"
    assert sent["argv"][sent["argv"].index("--tools") + 1] == ""
    assert "--safe-mode" in sent["argv"]
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
