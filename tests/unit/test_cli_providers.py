import asyncio
import json
import sys
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
    UsageReport,
)
from plural.agent.providers.cli import CLI_PROVIDERS, PRESETS
from plural.agent.providers.cli.answer import parse_answer, tool_call
from plural.agent.providers.cli.copilot import CopilotCliProvider
from plural.agent.providers.cli.gemini import GeminiCliProvider
from plural.agent.providers.cli.grok import GrokCliProvider
from plural.agent.providers.cli.opencode import OpencodeCliProvider
from plural.agent.providers.cli.prompt_cli import Event
from plural.agent.providers.cli.qwen import QwenCliProvider
from plural.agent.providers.preset import CLI_ADAPTERS

ANSWER = json.dumps(
    {"text": "Reading it.", "tool_calls": [{"name": "read", "args": {"path": "a"}}]}
)
REQUEST = LlmRequest(
    system="Be careful.",
    messages=(LlmMessage(role="user", content="Read a"),),
    tools=(ToolSchema(name="read", description="Read a file", parameters={"type": "object"}),),
)


def fake_cli(tmp_path: Path, lines: list[dict[str, object]], *, exit_code: int = 0) -> Path:
    """A CLI that records how it was called, then prints these JSON lines."""
    script = tmp_path / "fake-cli"
    record = tmp_path / "call.json"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "stdin = '' if sys.stdin.isatty() else sys.stdin.read()\n"
        f"json.dump({{'argv': sys.argv[1:], 'stdin': stdin, 'cwd': os.getcwd()}}, "
        f"open({str(record)!r}, 'w'))\n"
        f"for line in json.loads({json.dumps(lines)!r}):\n"
        "    print(json.dumps(line), flush=True)\n"
        f"sys.exit({exit_code})\n"
    )
    script.chmod(0o755)
    return script


async def run(provider: object, request: LlmRequest = REQUEST) -> list[object]:
    assert hasattr(provider, "stream")
    return [event async for event in provider.stream(request, cancel=asyncio.Event())]  # type: ignore[attr-defined]


def test_every_cli_has_a_preset_install_and_sign_in() -> None:
    assert {preset.adapter for preset in PRESETS} == set(CLI_PROVIDERS)
    assert set(CLI_PROVIDERS) == set(CLI_ADAPTERS)
    for adapter, provider in CLI_PROVIDERS.items():
        assert provider.adapter == adapter
        assert provider.label
        assert provider.binary
        assert provider.login


def test_an_answer_is_found_in_a_fence_or_after_a_sentence() -> None:
    fenced = f"Sure.\n```json\n{ANSWER}\n```"
    assert parse_answer(fenced) == ("Reading it.", [("read", {"path": "a"})])
    assert parse_answer("no json here") is None
    assert parse_answer('{"other": 1}') is None


async def test_copilot_streams_the_text_and_returns_the_tool_call(tmp_path: Path) -> None:
    half = len(ANSWER) // 2
    cli = fake_cli(
        tmp_path,
        [
            {"type": "assistant.message_delta", "data": {"deltaContent": ANSWER[:half]}},
            {"type": "assistant.message_delta", "data": {"deltaContent": ANSWER[half:]}},
            {"type": "assistant.message", "data": {"content": ANSWER}},
            {"type": "result", "exitCode": 0},
        ],
    )
    events = await run(CopilotCliProvider(model="gpt-5", workspace=tmp_path, cli=str(cli)))
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "Reading it."
    calls = [e.call for e in events if isinstance(e, ToolCallReady)]
    assert [(c.name, c.args) for c in calls] == [("read", {"path": "a"})]
    assert events[-1] == Stop(reason="tool_use")
    sent = json.loads((tmp_path / "call.json").read_text())
    argv = sent["argv"]
    assert argv[argv.index("--model") + 1] == "gpt-5"
    assert argv[argv.index("--available-tools") + 1] == ""
    assert "Be careful." in argv[argv.index("-p") + 1]
    # The CLI's own tools see an empty folder, not the workspace.
    assert not sent["cwd"].startswith(str(tmp_path))


async def test_qwen_gets_the_request_on_stdin_and_reports_usage(tmp_path: Path) -> None:
    cli = fake_cli(
        tmp_path,
        [
            {"type": "assistant", "message": {"content": [{"type": "text", "text": ANSWER}]}},
            {
                "type": "result",
                "result": ANSWER,
                "usage": {"input_tokens": 10, "cache_read_input_tokens": 90, "output_tokens": 5},
            },
        ],
    )
    events = await run(QwenCliProvider(workspace=tmp_path, cli=str(cli)))
    usage = next(e for e in events if isinstance(e, UsageReport)).usage
    assert usage.prompt_tokens == 100
    sent = json.loads((tmp_path / "call.json").read_text())
    assert "Read a" in sent["stdin"]
    assert "--model" not in sent["argv"]
    assert "-m" not in sent["argv"]


async def test_a_plain_reply_without_json_is_the_text(tmp_path: Path) -> None:
    cli = fake_cli(tmp_path, [{"type": "message", "role": "assistant", "content": "hello"}])
    events = await run(GeminiCliProvider(workspace=tmp_path, cli=str(cli)))
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "hello"
    assert events[-1] == Stop(reason="end_turn")


async def test_a_cli_error_names_how_to_sign_in(tmp_path: Path) -> None:
    cli = fake_cli(tmp_path, [{"type": "error", "error": {"name": "AuthError"}}], exit_code=1)
    with pytest.raises(ProviderError, match="opencode auth login"):
        await run(OpencodeCliProvider(workspace=tmp_path, cli=str(cli)))


async def test_a_tool_plural_does_not_have_goes_back_to_the_model(tmp_path: Path) -> None:
    # The run tells the model the tool does not exist, so it can try again; it does not end.
    answer = json.dumps({"text": "", "tool_calls": [{"name": "shell", "args": {}}]})
    cli = fake_cli(tmp_path, [{"type": "assistant.message", "data": {"content": answer}}])
    events = await run(CopilotCliProvider(workspace=tmp_path, cli=str(cli)))
    (call,) = [event.call for event in events if isinstance(event, ToolCallReady)]
    assert call.name == "shell"


def test_opencode_counts_the_cached_prompt_apart() -> None:
    provider = OpencodeCliProvider(workspace=Path(), cli=sys.executable)
    event = provider.parse(
        {
            "type": "step_finish",
            "part": {"tokens": {"input": 7, "output": 3, "cache": {"read": 40, "write": 2}}},
        }
    )
    assert event is not None
    assert event.usage is not None
    assert (event.usage.input_tokens, event.usage.cache_read_tokens) == (7, 40)
    assert provider.parse({"type": "text", "part": {"text": "hi"}}) == Event(message="hi")


def test_a_bad_tool_call_becomes_an_error_for_the_model() -> None:
    assert tool_call({"name": "read", "args": '{"path": "a"}'}).args == {"path": "a"}
    assert tool_call({"name": "read", "args": {"path": "a"}}).args == {"path": "a"}
    broken = tool_call({"name": "read", "args": "{'path': 'a'"})
    assert broken.parse_error is not None
    assert broken.parse_error.startswith("args are not valid JSON")
    assert tool_call({"name": "read", "args": "[1]"}).parse_error == "args must be a JSON object"
    assert tool_call("nonsense").parse_error == "a tool call is an object"


async def test_grok_streams_its_answer_and_adds_up_each_request(tmp_path: Path) -> None:
    half = len(ANSWER) // 2
    usage = {"input_tokens": 1000, "cache_read_input_tokens": 800, "output_tokens": 20}
    cli = fake_cli(
        tmp_path,
        [
            {"type": "text", "data": "Let me look around first."},
            {"type": "usage", "usage": usage},
            {"type": "tool_call", "toolName": "list_dir"},
            {"type": "text", "data": ANSWER[:half]},
            {"type": "text", "data": ANSWER[half:]},
            {"type": "usage", "usage": {**usage, "input_tokens": 1500}},
        ],
    )
    events = await run(GrokCliProvider(workspace=tmp_path, cli=str(cli)))
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "Reading it."
    assert [e.call.name for e in events if isinstance(e, ToolCallReady)] == ["read"]
    report = next(e for e in events if isinstance(e, UsageReport))
    # Grok's input tokens leave the cached part out.
    assert report.usage.prompt_tokens == 1800 + 2300
    assert report.usage.cache_read_tokens == 1600
    assert report.last is not None
    assert report.last.prompt_tokens == 2300


async def test_a_cli_that_says_nothing_is_an_error_not_an_answer(tmp_path: Path) -> None:
    cli = fake_cli(tmp_path, [{"type": "something_unknown"}])
    with pytest.raises(ProviderError, match="no answer"):
        await run(GrokCliProvider(workspace=tmp_path, cli=str(cli)))
