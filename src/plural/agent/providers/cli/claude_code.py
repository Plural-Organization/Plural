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
    ProviderActivity,
    ProviderError,
    Stop,
    TextDelta,
    ToolCallReady,
    ToolCallRequest,
    UsageReport,
)
from plural.agent.providers.cli.answer import TextFieldStream
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


INSTRUCTIONS = (
    "Continue this conversation. The available Plural tools and then each message of the "
    "conversation follow as JSON blocks. You have no tools of your own: these tools cannot be "
    "called directly, only through your structured answer. When a tool is needed, return its "
    "exact name and JSON arguments in tool_calls; Plural will request approval and run it. Do "
    "not claim a tool has run before its result appears in a later message. Images a message "
    "lists follow it under the same label. Otherwise answer in text."
)

# Claude Code's tool for the answer that `--json-schema` asks for.
ANSWER_TOOL = "StructuredOutput"


def _input(request: LlmRequest) -> bytes:
    """One stream-json user message: the instructions, the tools, then each message in turn.

    Every `claude -p` call starts fresh, so the whole conversation goes along each time. Each
    message is a block of its own after the tools, so a call repeats the blocks of the one before
    it from the start and the provider's prompt cache serves them instead of a full-price prompt.
    An image follows the message it belongs to.
    """
    tools = [tool.model_dump(mode="json") for tool in request.tools]
    content: list[dict[str, Any]] = [
        {"type": "text", "text": INSTRUCTIONS},
        {"type": "text", "text": json.dumps({"tools": tools}, ensure_ascii=False)},
    ]
    count = 0
    for message in request.messages:
        dumped = message.model_dump(mode="json", exclude_none=True, exclude={"images"})
        images: list[dict[str, Any]] = []
        for image in message.images:
            count += 1
            label = f"image {count}"
            dumped.setdefault("images", []).append(label)
            images.append({"type": "text", "text": f"[{label}]"})
            images.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": image.media_type,
                        "data": image.data,
                    },
                }
            )
        content.append(
            {"type": "text", "text": json.dumps({"message": dumped}, ensure_ascii=False)}
        )
        content.extend(images)
    line = {"type": "user", "message": {"role": "user", "content": content}}
    return (json.dumps(line, ensure_ascii=False) + "\n").encode()


def _usage(data: object) -> Usage | None:
    if not isinstance(data, dict):
        return None
    usage = cast("dict[str, object]", data)

    def count(key: str) -> int:
        value = usage.get(key)
        return value if isinstance(value, int) else 0

    return Usage(
        input_tokens=count("input_tokens"),
        output_tokens=count("output_tokens"),
        cache_read_tokens=count("cache_read_input_tokens"),
        cache_write_tokens=count("cache_creation_input_tokens"),
    )


def _last_usage(usage: object) -> Usage | None:
    """The last request's usage, which a result's `iterations` lists after the others."""
    if not isinstance(usage, dict):
        return None
    iterations = cast("dict[str, object]", usage).get("iterations")
    if not isinstance(iterations, list) or not iterations:
        return None
    return _usage(cast("list[object]", iterations)[-1])


def _native_calls(message: dict[str, object], names: set[str]) -> tuple[str, list[ToolCallRequest]]:
    """The text and the Plural tools an assistant message called directly, as if its own.

    Claude Code has none of them, so it would only answer "No such tool available"; the calls
    are taken as if the model had returned them in its structured answer.
    """
    content = message.get("content")
    text: list[str] = []
    calls: list[ToolCallRequest] = []
    for raw in cast("list[object]", content) if isinstance(content, list) else []:
        if not isinstance(raw, dict):
            continue
        block = cast("dict[str, object]", raw)
        name = block.get("name")
        args = block.get("input")
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            text.append(cast("str", block["text"]))
        elif (
            block.get("type") == "tool_use"
            and isinstance(name, str)
            and name in names
            and isinstance(args, dict)
        ):
            calls.append(
                ToolCallRequest(
                    id=f"toolu_{uuid4().hex}",
                    name=name,
                    args=cast("dict[str, JsonValue]", args),
                )
            )
    return "".join(text).strip(), calls


def _window(result: dict[str, object]) -> int | None:
    """The context window in a result's per-model usage, the largest if several models ran."""
    models = result.get("modelUsage")
    if not isinstance(models, dict):
        return None
    windows = [
        window
        for usage in cast("dict[str, object]", models).values()
        if isinstance(usage, dict)
        and isinstance(window := cast("dict[str, object]", usage).get("contextWindow"), int)
    ]
    return max(windows, default=None)


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
        self._window: int | None = None

    async def context_window(self) -> int | None:
        """The window Claude Code reported with its last answer."""
        return self._window

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
            "--input-format",
            "stream-json",
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
        process.stdin.write(_input(request))
        await process.stdin.drain()
        process.stdin.close()
        stderr_reader = asyncio.create_task(process.stderr.read())
        stopping = asyncio.create_task(cancel.wait())
        text_stream = TextFieldStream()
        streamed_plain_text = ""
        # Text written outside the structured answer, which usually repeats it.
        loose_text = ""
        result: dict[str, object] | None = None
        names = {tool.name for tool in request.tools}
        # The block being written; only the answer's own input carries its text.
        block_tool: str | None = None
        # Each request's usage by message id, while no result sums them.
        requests: dict[str, Usage] = {}
        native: tuple[str, list[ToolCallRequest]] | None = None
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
                message = event.get("message")
                if event.get("type") == "assistant" and isinstance(message, dict):
                    message_data = cast("dict[str, object]", message)
                    usage = _usage(message_data.get("usage"))
                    if usage is not None:
                        requests[str(message_data.get("id"))] = usage
                    text, calls = _native_calls(message_data, names)
                    if calls:
                        # Claude Code would go on to answer that it has no such tool.
                        native = (text, calls)
                        process.kill()
                        break
                if event.get("type") != "stream_event":
                    yield ProviderActivity(source=str(event.get("type") or "event"))
                    continue
                inner = event.get("event")
                if not isinstance(inner, dict):
                    continue
                inner_data = cast("dict[str, object]", inner)
                block = inner_data.get("content_block")
                if inner_data.get("type") == "content_block_start" and isinstance(block, dict):
                    block_name = cast("dict[str, object]", block).get("name")
                    block_tool = block_name if isinstance(block_name, str) else None
                delta = inner_data.get("delta")
                if not isinstance(delta, dict):
                    # Block starts and stops and message deltas: the model is still working.
                    yield ProviderActivity(source=str(inner_data.get("type") or "event"))
                    continue
                delta_data = cast("dict[str, object]", delta)
                match delta_data.get("type"):
                    case "text_delta":
                        text = delta_data.get("text")
                        if isinstance(text, str):
                            loose_text += text
                        yield ProviderActivity(source="text_delta")
                    case "input_json_delta":
                        partial = delta_data.get("partial_json")
                        text = (
                            text_stream.feed(partial)
                            if isinstance(partial, str) and block_tool in {None, ANSWER_TOOL}
                            else ""
                        )
                        if text:
                            streamed_plain_text += text
                            yield TextDelta(text=text)
                        else:
                            # The answer's tool calls, a long file for instance, carry no text.
                            yield ProviderActivity(source="input_json_delta")
                    case other:
                        yield ProviderActivity(source=str(other or "delta"))
            await process.wait()
        finally:
            stopping.cancel()
            if process.returncode is None:
                process.kill()
                await process.wait()
            await asyncio.gather(stderr_reader, stopping, return_exceptions=True)
        if cancel.is_set():
            return
        if native is not None:
            text, calls = native
            if text and not streamed_plain_text:
                yield TextDelta(text=text)
            for call in calls:
                yield ToolCallReady(call=call)
            if requests:
                spent = list(requests.values())
                yield UsageReport(usage=sum(spent[1:], spent[0]), last=spent[-1])
            yield Stop(reason="tool_use")
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
        if not text and not streamed_plain_text:
            text = loose_text.strip()
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
        self._window = _window(result) or self._window
        # A result sums every request Claude Code made for this answer; the last one holds the
        # conversation as it now stands.
        usage = _usage(result.get("usage"))
        if usage is not None:
            yield UsageReport(usage=usage, last=_last_usage(result.get("usage")))
        yield Stop(reason="tool_use" if calls else "end_turn")
