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
            "json",
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
                env={
                    key: value
                    for key, value in os.environ.items()
                    if key not in {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"}
                },
            )
        except OSError as error:
            raise ProviderError(f"Could not start Claude Code: {error}") from error
        communicating = asyncio.create_task(process.communicate(_prompt(request).encode()))
        stopping = asyncio.create_task(cancel.wait())
        try:
            done, _ = await asyncio.wait(
                {communicating, stopping}, return_when=asyncio.FIRST_COMPLETED
            )
            if stopping in done and communicating not in done:
                return
            stdout, stderr = await communicating
        finally:
            stopping.cancel()
            if process.returncode is None:
                process.kill()
                await process.wait()
            if not communicating.done():
                communicating.cancel()
            await asyncio.gather(communicating, stopping, return_exceptions=True)
        if cancel.is_set():
            return
        try:
            decoded: object = json.loads(stdout)
        except (ValueError, UnicodeDecodeError) as error:
            detail = stderr.decode(errors="replace").strip()[:300]
            raise ProviderError(
                f"Claude Code did not return JSON: {detail or 'check claude auth login'}"
            ) from error
        if not isinstance(decoded, dict):
            raise ProviderError("Claude Code returned an invalid response")
        result = cast("dict[str, object]", decoded)
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
        if text:
            yield TextDelta(text=text)
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
