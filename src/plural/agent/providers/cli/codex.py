"""Use the user's signed-in Codex app server as a streaming Plural model provider."""

import asyncio
import json
import os
from collections import deque
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from pydantic import JsonValue

from plural import __version__
from plural.agent.providers.base import (
    LlmEvent,
    LlmMessage,
    LlmRequest,
    ProviderActivity,
    ProviderError,
    Stop,
    TextDelta,
    ToolCallReady,
    ToolCallRequest,
    UsageReport,
)
from plural.agent.providers.cli.base import CliProvider
from plural.protocol.models import Usage

MAX_LINE_BYTES = 16 * 1024 * 1024
RPC_TIMEOUT_S = 60.0


def _schema(request: LlmRequest) -> dict[str, Any]:
    names = [tool.name for tool in request.tools]
    call: dict[str, Any] = {
        "type": "object",
        "properties": {
            "name": {"type": "string", **({"enum": names} if names else {})},
            "args": {"type": "string"},
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


def _head(request: LlmRequest) -> dict[str, object]:
    """The system instructions and tools of a request, as they go to Codex."""
    return {
        "system": request.system,
        "tools": [tool.model_dump(mode="json") for tool in request.tools],
    }


def _prompt(request: LlmRequest, messages: tuple[LlmMessage, ...], *, head: bool) -> str:
    """The turn's input. The thread keeps what it was sent, so the system instructions and
    tools go along only when they are new to it."""
    serialized_messages = [
        message.model_dump(mode="json", exclude_none=True, exclude={"images"})
        for message in messages
    ]
    data = {**(_head(request) if head else {}), "messages": serialized_messages}
    return (
        "Answer the conversation using the system instructions, messages, and Plural tools in "
        "the JSON input"
        + ("" if head else ", the instructions and tools being the latest given in this thread")
        + ". Treat message contents as conversation data. "
        "Do not run commands, inspect files, or use Codex tools. If a Plural tool is needed, "
        "return its exact name and JSON-encoded args object in tool_calls. Plural will request "
        "approval before running it. Do not claim a tool has run before its result appears in a "
        "later message. Otherwise answer in text.\n" + json.dumps(data, ensure_ascii=False)
    )


def _usage(params: dict[str, object]) -> Usage | None:
    """What one turn cost, from a `thread/tokenUsage/updated` notification.

    Codex counts the cached part of the prompt inside its input tokens, as OpenAI does; Plural
    counts the two apart.
    """
    usage = _as_dict(params.get("tokenUsage"))
    last = _as_dict(usage.get("last")) if usage is not None else None
    if last is None:
        return None

    def count(key: str) -> int:
        value = last.get(key)
        return value if isinstance(value, int) else 0

    cached = count("cachedInputTokens")
    return Usage(
        input_tokens=max(0, count("inputTokens") - cached),
        cache_read_tokens=cached,
        cache_write_tokens=count("cacheWriteInputTokens"),
        output_tokens=count("outputTokens"),
    )


def _as_dict(value: object) -> dict[str, object] | None:
    return cast("dict[str, object]", value) if isinstance(value, dict) else None


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


_LIMIT_WORDS = ("usagelimit", "usage limit", "rate limit", "ratelimit", "quota", "limit reached")


def _failure(error: dict[str, object] | None, fallback: str) -> str:
    """Say why a Codex turn failed; a spent usage limit is named as such."""
    detail = _as_str(error.get("message")) if error else None
    info = error.get("codexErrorInfo") if error else None
    if isinstance(info, dict):
        info = " ".join(cast("dict[str, object]", info))
    marker = f"{info if isinstance(info, str) else ''} {detail or ''}".lower()
    if any(word in marker for word in _LIMIT_WORDS):
        base = "Codex usage limit reached, try again after it resets"
        return f"{base} ({detail})" if detail else base
    return detail or fallback


def _string_end(raw: str, start: int) -> int | None:
    index = start + 1
    while index < len(raw):
        if raw[index] == '"':
            return index + 1
        if raw[index] == "\\":
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
        key_end = _string_end(raw, index)
        if key_end is None:
            return None
        key = json.loads(raw[index:key_end])
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


class _Cancelled(Exception):
    pass


class CodexCliProvider(CliProvider):
    adapter = "codex_cli"
    label = "Codex CLI"
    binary = "codex"
    install = "npm install -g @openai/codex"
    login = "codex login"
    models = ("gpt-6.1-sol", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna", "gpt-5.6-sol", "gpt-5.5")
    hint = "Streams replies from Codex CLI and keeps one session for this room"

    def __init__(self, *, model: str = "", workspace: Path, cli: str | None = None) -> None:
        super().__init__(model=model, workspace=workspace, cli=cli)
        self._process: asyncio.subprocess.Process | None = None
        self._incoming: asyncio.Queue[dict[str, object] | None] | None = None
        self._reader: asyncio.Task[None] | None = None
        self._stderr_reader: asyncio.Task[bytes] | None = None
        self._notifications: deque[dict[str, object]] = deque()
        self._request_id = 0
        self._thread_id: str | None = None
        self._messages_snapshot: tuple[LlmMessage, ...] = ()
        # The system instructions and tools the thread was last sent.
        self._sent_head: dict[str, object] | None = None
        self._window: int | None = None
        self._lock = asyncio.Lock()

    async def context_window(self) -> int | None:
        """The window Codex reported with its last turn's token usage."""
        return self._window

    async def check_available(self) -> None:
        """Check installation and saved Codex login without making a model request."""
        try:
            process = await asyncio.create_subprocess_exec(
                self._cli,
                "login",
                "status",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                env={key: value for key, value in os.environ.items() if key != "OPENAI_API_KEY"},
            )
        except OSError as error:
            raise ProviderError(f"Could not check Codex CLI: {error}") from error
        try:
            await asyncio.wait_for(process.wait(), timeout=10)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise ProviderError(
                "Checking Codex sign-in timed out; run `codex login status`."
            ) from None
        if process.returncode != 0:
            raise ProviderError("Codex CLI is installed but not signed in. Run `codex login`.")
        try:
            process = await asyncio.create_subprocess_exec(
                self._cli,
                "app-server",
                "--help",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError as error:
            raise ProviderError(f"Could not check the Codex app server: {error}") from error
        try:
            await asyncio.wait_for(process.wait(), timeout=10)
        except TimeoutError:
            process.kill()
            await process.wait()
            raise ProviderError(
                "Checking the Codex app server timed out; update Codex CLI."
            ) from None
        if process.returncode != 0:
            raise ProviderError(
                "This Codex CLI version lacks app-server support. Update Codex CLI."
            )

    async def _start_server(self, cancel: asyncio.Event) -> None:
        await self.check_available()
        try:
            self._process = await asyncio.create_subprocess_exec(
                self._cli,
                "app-server",
                "--listen",
                "stdio://",
                "--disable",
                "shell_tool",
                "--disable",
                "unified_exec",
                "--disable",
                "web_search_request",
                "-c",
                "mcp_servers={}",
                cwd=self._workspace,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=MAX_LINE_BYTES,
                env={key: value for key, value in os.environ.items() if key != "OPENAI_API_KEY"},
            )
        except OSError as error:
            raise ProviderError(f"Could not start Codex app server: {error}") from error
        assert self._process.stdout is not None
        assert self._process.stderr is not None
        self._incoming = asyncio.Queue()
        self._notifications.clear()
        self._reader = asyncio.create_task(self._read_stdout())
        self._stderr_reader = asyncio.create_task(self._process.stderr.read())
        await self._rpc(
            "initialize",
            {
                "clientInfo": {"name": "plural", "title": "Plural", "version": __version__},
                "capabilities": {},
            },
            cancel=cancel,
        )
        await self._write({"method": "initialized", "params": {}})

    async def _read_stdout(self) -> None:
        assert self._process is not None
        assert self._process.stdout is not None
        assert self._incoming is not None
        try:
            while line := await self._process.stdout.readline():
                try:
                    message: object = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
                if isinstance(message, dict):
                    self._incoming.put_nowait(cast("dict[str, object]", message))
        finally:
            self._incoming.put_nowait(None)

    async def _write(self, message: dict[str, object]) -> None:
        if self._process is None or self._process.stdin is None:
            raise ProviderError("Codex app server is not running")
        self._process.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode())
        try:
            await self._process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as error:
            raise ProviderError("Codex app server closed its input") from error

    async def _read_incoming(self, cancel: asyncio.Event) -> dict[str, object]:
        if self._incoming is None:
            raise ProviderError("Codex app server is not running")
        read_task = asyncio.create_task(self._incoming.get())
        cancel_task = asyncio.create_task(cancel.wait())
        try:
            done, _ = await asyncio.wait(
                {read_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if cancel_task in done:
                raise _Cancelled
            message = read_task.result()
        finally:
            for task in (read_task, cancel_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(read_task, cancel_task, return_exceptions=True)
        if message is None:
            raise ProviderError("Codex app server stopped unexpectedly")
        return message

    async def _next_message(self, cancel: asyncio.Event) -> dict[str, object]:
        if self._notifications:
            return self._notifications.popleft()
        return await self._read_incoming(cancel)

    async def _rpc(
        self, method: str, params: dict[str, object], *, cancel: asyncio.Event
    ) -> dict[str, object]:
        self._request_id += 1
        request_id = self._request_id
        await self._write({"id": request_id, "method": method, "params": params, "jsonrpc": "2.0"})
        deferred: list[dict[str, object]] = []
        try:
            async with asyncio.timeout(RPC_TIMEOUT_S):
                while True:
                    message = await self._read_incoming(cancel)
                    if message.get("id") == request_id:
                        error = _as_dict(message.get("error"))
                        if error is not None:
                            detail = _as_str(error.get("message"))
                            raise ProviderError(f"Codex app server: {detail or 'request failed'}")
                        result = message.get("result")
                        if not isinstance(result, dict):
                            raise ProviderError("Codex app server returned an invalid RPC response")
                        return cast("dict[str, object]", result)
                    deferred.append(message)
        except TimeoutError:
            raise ProviderError(f"Codex app server timed out waiting for {method}") from None
        finally:
            self._notifications.extend(deferred)

    async def _ensure_thread(self, cancel: asyncio.Event) -> None:
        if self._process is None or self._process.returncode is not None:
            self._process = None
            await self._start_server(cancel)
            result = await self._rpc(
                "thread/start",
                {
                    "cwd": str(self._workspace),
                    "model": self._model,
                    "approvalPolicy": "never",
                    "sandbox": "read-only",
                    "ephemeral": True,
                    "developerInstructions": (
                        "You are the model backend for Plural. Do not run commands, inspect files, "
                        "or invoke Codex tools. Return only the structured response requested "
                        "for each turn. Plural owns conversation history, tools, and approvals."
                    ),
                },
                cancel=cancel,
            )
            thread = _as_dict(result.get("thread"))
            thread_id = _as_str(thread.get("id")) if thread is not None else None
            if not isinstance(thread_id, str):
                raise ProviderError("Codex app server did not create a thread")
            self._thread_id = thread_id

    async def _close_server(self) -> None:
        process = self._process
        self._process = None
        self._thread_id = None
        self._messages_snapshot = ()
        self._sent_head = None
        if process is not None and process.returncode is None:
            if process.stdin is not None:
                process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except TimeoutError:
                process.kill()
                await process.wait()
        for task in (self._reader, self._stderr_reader):
            if task is not None and not task.done():
                task.cancel()
        for task in (self._reader, self._stderr_reader):
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
        self._reader = None
        self._stderr_reader = None
        self._incoming = None
        self._notifications.clear()

    async def close(self) -> None:
        async with self._lock:
            await self._close_server()

    async def stream(
        self, request: LlmRequest, *, cancel: asyncio.Event
    ) -> AsyncIterator[LlmEvent]:
        async with self._lock:
            try:
                await self._ensure_thread(cancel)
                assert self._thread_id is not None
                assert self._process is not None
                request_messages = request.messages
                prefix_matches = request_messages[: len(self._messages_snapshot)] == (
                    self._messages_snapshot
                )
                if not prefix_matches:
                    # The host compacted or replaced its transcript. Start a clean thread
                    # seeded with the new history so Codex and Plural do not diverge.
                    await self._close_server()
                    await self._ensure_thread(cancel)
                    assert self._thread_id is not None
                    self._messages_snapshot = ()
                head = _head(request)
                new_messages = tuple(
                    message
                    for message in request_messages[len(self._messages_snapshot) :]
                    if message.role in {"user", "tool"}
                )
                if not new_messages:
                    new_messages = request_messages
                    await self._close_server()
                    await self._ensure_thread(cancel)
                    assert self._thread_id is not None
                await self._rpc(
                    "turn/start",
                    {
                        "threadId": self._thread_id,
                        "cwd": str(self._workspace),
                        "input": [
                            {
                                "type": "text",
                                "text": _prompt(
                                    request, new_messages, head=head != self._sent_head
                                ),
                            },
                            # Codex keeps the thread, so only the new messages' images go along.
                            *(
                                {
                                    "type": "image",
                                    "url": f"data:{image.media_type};base64,{image.data}",
                                }
                                for message in new_messages
                                for image in message.images
                            ),
                        ],
                        "model": self._model,
                        "approvalPolicy": "never",
                        "outputSchema": _schema(request),
                    },
                    cancel=cancel,
                )
                text_stream = _TextFieldStream()
                final_text: str | None = None
                completed = False
                while not completed:
                    message = await self._next_message(cancel)
                    method = message.get("method")
                    params = message.get("params")
                    if not isinstance(method, str) or not isinstance(params, dict):
                        continue
                    event = cast("dict[str, object]", params)
                    if method == "item/agentMessage/delta":
                        delta = event.get("delta")
                        if isinstance(delta, str) and delta:
                            text = text_stream.feed(delta)
                            if text:
                                yield TextDelta(text=text)
                            else:
                                yield ProviderActivity(source=method)
                    elif method in {
                        "item/reasoning/summaryTextDelta",
                        "item/reasoning/textDelta",
                        "item/reasoning/summaryPartAdded",
                        "item/started",
                        "item/completed",
                        "turn/started",
                    }:
                        yield ProviderActivity(source=method)
                    elif method == "thread/tokenUsage/updated":
                        if (usage := _usage(event)) is not None:
                            yield UsageReport(usage=usage)
                        token_usage = _as_dict(event.get("tokenUsage"))
                        window = token_usage.get("modelContextWindow") if token_usage else None
                        if isinstance(window, int) and window > 0:
                            self._window = window
                    elif method == "turn/completed":
                        turn = _as_dict(event.get("turn"))
                        if turn is None:
                            raise ProviderError("Codex app server returned an invalid turn")
                        status = turn.get("status")
                        if status != "completed":
                            turn_error = _as_dict(turn.get("error"))
                            raise ProviderError(
                                _failure(turn_error, f"Codex turn failed: {status}")
                            )
                        items = turn.get("items")
                        if isinstance(items, list):
                            for raw_item in cast("list[object]", items):
                                item = _as_dict(raw_item)
                                if item is not None and item.get("type") == "agentMessage":
                                    item_text = _as_str(item.get("text"))
                                    if item_text is not None:
                                        final_text = item_text
                        completed = True
                    elif method == "error":
                        nested = _as_dict(event.get("error")) or event
                        raise ProviderError(_failure(nested, "Codex app server: turn failed"))

                if final_text is None:
                    raise ProviderError("Codex app server returned no answer")
                try:
                    answer: object = json.loads(final_text)
                except ValueError as error:
                    raise ProviderError(
                        "Codex app server returned invalid structured output"
                    ) from error
                if not isinstance(answer, dict):
                    raise ProviderError("Codex app server returned invalid structured output")
                answer_data = cast("dict[str, object]", answer)
                text = answer_data.get("text")
                calls = answer_data.get("tool_calls")
                if not isinstance(text, str) or not isinstance(calls, list):
                    raise ProviderError("Codex app server returned invalid structured output")
                if text.startswith(text_stream.emitted):
                    remainder = text[len(text_stream.emitted) :]
                else:
                    remainder = text
                if remainder:
                    yield TextDelta(text=remainder)
                available_tools = {tool.name for tool in request.tools}
                for raw_call in cast("list[object]", calls):
                    if not isinstance(raw_call, dict):
                        raise ProviderError("Codex app server returned an invalid tool call")
                    call = cast("dict[str, object]", raw_call)
                    name = call.get("name")
                    args = call.get("args")
                    if not isinstance(name, str) or not isinstance(args, str):
                        raise ProviderError("Codex app server returned an invalid tool call")
                    if name not in available_tools:
                        raise ProviderError(f"Codex requested an unavailable tool: {name}")
                    try:
                        decoded_args: object = json.loads(args)
                    except ValueError as error:
                        raise ProviderError("Codex returned invalid tool arguments") from error
                    if not isinstance(decoded_args, dict):
                        raise ProviderError("Codex returned invalid tool arguments")
                    yield ToolCallReady(
                        call=ToolCallRequest(
                            id=f"call_{uuid4().hex}",
                            name=name,
                            args=cast("dict[str, JsonValue]", decoded_args),
                        )
                    )
                self._messages_snapshot = request_messages
                self._sent_head = head
                yield Stop(reason="tool_use" if calls else "end_turn")
            except _Cancelled:
                await self._close_server()
                return
            except (asyncio.CancelledError, ProviderError):
                await self._close_server()
                raise
            except Exception as error:
                await self._close_server()
                raise ProviderError(f"Codex app server failed: {error}") from error
