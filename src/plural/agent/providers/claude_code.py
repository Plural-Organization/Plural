"""Use the installed Claude Code CLI as a genuine, non-interactive model backend."""

import asyncio
import json
import os
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from pydantic import JsonValue

from plural.agent.providers.base import (
    LlmEvent,
    LlmRequest,
    ProviderError,
    Stop,
    TextDelta,
    ToolCallReady,
    ToolCallRequest,
    UsageReport,
)
from plural.protocol.models import Usage

DEFAULT_MODEL = "claude-sonnet-5-5"


def _schema(request: LlmRequest) -> dict[str, Any]:
    names = [tool.name for tool in request.tools]
    call: dict[str, Any] = {
        "type": "object",
        "properties": {
            "name": {"type": "string", **({"enum": names} if names else {})},
            "args": {"type": "object"},
        },
        "required": ["name", "args"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "tool_calls": {
                "type": "array",
                "items": call,
                **({"maxItems": 0} if not names else {}),
            },
        },
        "required": ["text", "tool_calls"],
        "additionalProperties": False,
    }


def _prompt(request: LlmRequest) -> str:
    messages = [message.model_dump(mode="json", exclude_none=True) for message in request.messages]
    tools = [tool.model_dump(mode="json") for tool in request.tools]
    return (
        "Continue this conversation. Messages and available Plural tools are JSON data below. "
        "When a tool is needed, return its exact name and JSON arguments in tool_calls; "
        "Plural will request approval and run it. Do not claim a tool has run before its "
        "result appears in a later message. Otherwise answer in text.\n"
        + json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False)
    )


def _string_end(raw: str, start: int) -> int | None:
    """Return the position after a complete JSON string, or None while it is partial."""
    index = start + 1
    while index < len(raw):
        char = raw[index]
        if char == '"':
            return index + 1
        if char == "\\":
            if index + 1 >= len(raw):
                return None
            index += 2
            if raw[index - 1] == "u":
                if len(raw) < index + 4:
                    return None
                index += 4
        else:
            index += 1
    return None


def _value_end(raw: str, start: int) -> int | None:
    if start >= len(raw):
        return None
    if raw[start] == '"':
        return _string_end(raw, start)
    depth = 0
    index = start
    while index < len(raw):
        char = raw[index]
        if char == '"':
            end = _string_end(raw, index)
            if end is None:
                return None
            index = end
            continue
        if char in "[{":
            depth += 1
        elif char in "]}":
            if depth == 0:
                return index
            depth -= 1
            if depth == 0:
                return index + 1
        elif char == "," and depth == 0:
            return index
        index += 1
    return None


def _text_value_start(raw: str) -> int | None:
    """Find the top-level `text` string in the incremental structured output."""
    index = 0
    while index < len(raw) and raw[index].isspace():
        index += 1
    if index >= len(raw) or raw[index] != "{":
        return None
    index += 1
    while index < len(raw):
        while index < len(raw) and (raw[index].isspace() or raw[index] == ","):
            index += 1
        if index >= len(raw) or raw[index] == "}":
            return None
        if raw[index] != '"':
            return None
        key_start = index
        key_end = _string_end(raw, index)
        if key_end is None:
            return None
        key = json.loads(raw[key_start:key_end])
        index = key_end
        while index < len(raw) and raw[index].isspace():
            index += 1
        if index >= len(raw) or raw[index] != ":":
            return None
        index += 1
        while index < len(raw) and raw[index].isspace():
            index += 1
        if key == "text":
            return index + 1 if index < len(raw) and raw[index] == '"' else None
        index = _value_end(raw, index)
        if index is None:
            return None
    return None


class _TextFieldStream:
    def __init__(self) -> None:
        self.raw = ""
        self.start: int | None = None
        self.emitted = ""

    def feed(self, fragment: str) -> str:
        self.raw += fragment
        if self.start is None:
            self.start = _text_value_start(self.raw)
        if self.start is None:
            return ""
        end = self.start
        while end < len(self.raw):
            char = self.raw[end]
            if char == '"':
                break
            if char == "\\":
                if end + 1 >= len(self.raw):
                    break
                if self.raw[end + 1] == "u":
                    if len(self.raw) < end + 6:
                        break
                    end += 6
                else:
                    end += 2
            else:
                end += 1
        try:
            decoded = json.loads(f'"{self.raw[self.start : end]}"')
        except json.JSONDecodeError:
            return ""
        if not isinstance(decoded, str) or not decoded.startswith(self.emitted):
            return ""
        delta = decoded[len(self.emitted) :]
        self.emitted = decoded
        return delta


class ClaudeCodeProvider:
    def __init__(
        self, *, model: str = DEFAULT_MODEL, workspace: Path, cli: str | None = None
    ) -> None:
        cli_path = cli or shutil.which("claude")
        if cli_path is None:
            raise ProviderError(
                "Claude Code CLI is missing. Install it, then run claude auth login."
            )
        self._cli = cli_path
        self._model = model
        self._workspace = workspace

    async def stream(
        self, request: LlmRequest, *, cancel: asyncio.Event
    ) -> AsyncIterator[LlmEvent]:
        command = [
            self._cli,
            "-p",
            "--safe-mode",
            "--tools",
            "",
            "--disallowedTools",
            "mcp__*",
            "--permission-mode",
            "dontAsk",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--json-schema",
            json.dumps(_schema(request)),
            "--model",
            self._model,
            "--system-prompt",
            request.system,
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=self._workspace,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=16 * 1024 * 1024,
                env={
                    key: value
                    for key, value in os.environ.items()
                    if key not in {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"}
                },
            )
        except OSError as error:
            raise ProviderError(f"Could not start Claude Code: {error}") from error
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        process.stdin.write(_prompt(request).encode())
        await process.stdin.drain()
        process.stdin.close()
        stderr_reader = asyncio.create_task(process.stderr.read())
        stopping = asyncio.create_task(cancel.wait())
        text_stream = _TextFieldStream()
        streamed_plain_text = ""
        result: dict[str, object] | None = None
        try:
            while True:
                line_reader = asyncio.create_task(process.stdout.readline())
                done, _ = await asyncio.wait(
                    {line_reader, stopping}, return_when=asyncio.FIRST_COMPLETED
                )
                if stopping in done:
                    line_reader.cancel()
                    await asyncio.gather(line_reader, return_exceptions=True)
                    return
                line = await line_reader
                if not line:
                    break
                try:
                    decoded: object = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
                if not isinstance(decoded, dict):
                    continue
                event = cast("dict[str, object]", decoded)
                if event.get("type") == "result":
                    result = event
                    continue
                if event.get("type") != "stream_event":
                    continue
                inner = event.get("event")
                if not isinstance(inner, dict):
                    continue
                delta = cast("dict[str, object]", inner).get("delta")
                if not isinstance(delta, dict):
                    continue
                delta_data = cast("dict[str, object]", delta)
                match delta_data.get("type"):
                    case "text_delta":
                        text = delta_data.get("text")
                        if isinstance(text, str) and text:
                            streamed_plain_text += text
                            yield TextDelta(text=text)
                    case "input_json_delta":
                        partial = delta_data.get("partial_json")
                        if isinstance(partial, str):
                            text = text_stream.feed(partial)
                            if text:
                                streamed_plain_text += text
                                yield TextDelta(text=text)
                    case _:
                        pass
            await process.wait()
        finally:
            stopping.cancel()
            if process.returncode is None:
                process.kill()
                await process.wait()
            await asyncio.gather(stderr_reader, stopping, return_exceptions=True)
        if cancel.is_set():
            return
        stderr = stderr_reader.result()
        if result is None:
            detail = stderr.decode(errors="replace").strip()[:300]
            raise ProviderError(
                f"Claude Code did not return a result: {detail or 'check claude auth login'}"
            )
        if process.returncode != 0 or result.get("is_error") is True:
            result_detail = result.get("result")
            detail = (
                result_detail
                if isinstance(result_detail, str)
                else stderr.decode(errors="replace").strip()
            )[:300]
            raise ProviderError(f"Claude Code: {detail or 'run claude auth login'}")
        decoded_answer = result.get("structured_output")
        if not isinstance(decoded_answer, dict):
            raise ProviderError(
                f"Claude Code: {str(result.get('result') or 'no structured answer')[:300]}"
            )
        answer = cast("dict[str, object]", decoded_answer)
        text = answer.get("text")
        calls = answer.get("tool_calls")
        if not isinstance(text, str) or not isinstance(calls, list):
            raise ProviderError("Claude Code returned an invalid answer")
        if text.startswith(streamed_plain_text):
            remaining_text = text[len(streamed_plain_text) :]
        else:
            remaining_text = text if streamed_plain_text == "" else ""
        if remaining_text:
            yield TextDelta(text=remaining_text)
        for raw_call in cast("list[object]", calls):
            if not isinstance(raw_call, dict):
                raise ProviderError("Claude Code returned an invalid tool call")
            call = cast("dict[str, object]", raw_call)
            name = call.get("name")
            args = call.get("args")
            if not isinstance(name, str) or not isinstance(args, dict):
                raise ProviderError("Claude Code returned an invalid tool call")
            tool_args = cast("dict[str, JsonValue]", args)
            if name not in {tool.name for tool in request.tools}:
                raise ProviderError(f"Claude Code requested an unavailable tool: {name}")
            yield ToolCallReady(
                call=ToolCallRequest(id=f"toolu_{uuid4().hex}", name=name, args=tool_args)
            )
        usage = result.get("usage")
        if isinstance(usage, dict):
            usage_data = cast("dict[str, object]", usage)

            def token_count(key: str) -> int:
                value = usage_data.get(key)
                return value if isinstance(value, int) else 0

            yield UsageReport(
                usage=Usage(
                    input_tokens=token_count("input_tokens"),
                    output_tokens=token_count("output_tokens"),
                    cache_read_tokens=token_count("cache_read_input_tokens"),
                    cache_write_tokens=token_count("cache_creation_input_tokens"),
                )
            )
        yield Stop(reason="tool_use" if calls else "end_turn")
