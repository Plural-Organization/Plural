"""Use the user's signed-in Codex app server as a streaming Plural model provider."""

import asyncio
import json
import os
from collections import deque
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import cast
from uuid import uuid4

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
    UsageReport,
)
from plural.agent.providers.cli.answer import tool_call
from plural.agent.providers.cli.base import CliProvider
from plural.protocol.models import Usage

MAX_LINE_BYTES = 16 * 1024 * 1024
RPC_TIMEOUT_S = 60.0


def _head(request: LlmRequest) -> dict[str, object]:
    """The system instructions and tools of a request, as they go to Codex."""
    return {
        "system": request.system,
        "tools": [tool.model_dump(mode="json") for tool in request.tools],
    }


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


class _Cancelled(Exception):
    pass


# Plural owns the prompt, tools and history, so what Codex would add of its own each turn is
# turned off: on its own Codex sent ~21.8k tokens for "say ok", with these ~8.2k. `-c` is used
# throughout because an unknown `--disable` feature stops the server, and an unknown key does not.
CODEX_TRIM = (
    # Codex's own shell and web search; user hooks would run on every turn; plugins, apps, goals,
    # image viewing and sleeping each add tools or instructions.
    *(
        f"features.{feature}=false"
        for feature in (
            "shell_tool",
            "unified_exec",
            "web_search_request",
            "hooks",
            "plugins",
            "apps",
            "goals",
            "view_image",
            "sleep_tool",
        )
    ),
    # The list of skills, Codex's collaboration mode and sandbox rules, and its cwd and shell.
    "skills.include_instructions=false",
    "include_collaboration_mode_instructions=false",
    "include_permissions_instructions=false",
    "include_environment_context=false",
)

# Codex's own system prompt, a coding agent's, replaced by this one.
# Said as what to do rather than what not to: told "do not inspect files", a small model takes it
# for "you cannot look at the workspace" and stops before it starts.
BASE_INSTRUCTIONS = (
    "You are the model behind Plural, a coding agent shared by a room of people. Codex's own "
    "tools are switched off; the tools you have are Plural's. Call them to read, search and "
    "change files and to run commands: Plural runs each call in the workspace, with the room's "
    "approval where it is needed, and gives you the result. apply_patch cannot write here: "
    "change files with edit or write. edit's old text is matched exactly, not as a pattern."
)


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
        # Tool calls Codex asked for and waits on, in its open turn: request id and call id.
        self._pending: list[tuple[object, str]] = []

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
                "-c",
                "mcp_servers={}",
                *(arg for setting in CODEX_TRIM for arg in ("-c", setting)),
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
                # Plural's tools go to the model as Codex dynamic tools, an experimental part of
                # the protocol.
                "capabilities": {"experimentalApi": True},
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

    async def _ensure_thread(self, request: LlmRequest, cancel: asyncio.Event) -> None:
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
                    # Plural's own system prompt in place of Codex's, and Plural's tools as
                    # tools the model calls natively: Codex asks Plural to run each one.
                    "baseInstructions": f"{BASE_INSTRUCTIONS}\n\n{request.system}".strip(),
                    "dynamicTools": [
                        {
                            "type": "function",
                            "name": tool.name,
                            "description": tool.description,
                            "inputSchema": tool.parameters,
                        }
                        for tool in request.tools
                    ],
                },
                cancel=cancel,
            )
            self._sent_head = _head(request)
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
        self._pending = []
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
        """One step of the conversation. Codex runs a turn until it asks for a tool, and Plural
        runs the tool; the next request brings the result, which goes back into the same turn.
        """
        async with self._lock:
            try:
                async for event in self._step(request, cancel):
                    yield event
            except _Cancelled:
                await self._close_server()
                return
            except (asyncio.CancelledError, ProviderError):
                await self._close_server()
                raise
            except Exception as error:
                await self._close_server()
                raise ProviderError(f"Codex app server failed: {error}") from error

    async def _step(self, request: LlmRequest, cancel: asyncio.Event) -> AsyncIterator[LlmEvent]:
        held = len(self._messages_snapshot)
        fresh = request.messages[held:]
        alive = self._process is not None and self._process.returncode is None
        continuing = (
            alive
            and self._thread_id is not None
            and _head(request) == self._sent_head
            and request.messages[:held] == self._messages_snapshot
            and any(message.role != "assistant" for message in fresh)
        )
        said = [message for message in fresh if message.role == "user"]
        if continuing and self._pending and not said:
            # The results of the calls the open turn waits on.
            results = {message.tool_call_id: message for message in fresh if message.role == "tool"}
            for request_id, call_id in self._pending:
                result = results.get(call_id)
                await self._write(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "contentItems": [
                                {
                                    "type": "inputText",
                                    "text": result.content if result else "Not run.",
                                }
                            ],
                            "success": result is not None and not result.is_error,
                        },
                    }
                )
            self._pending = []
        else:
            if not continuing or self._pending:
                # A new conversation, a changed prompt or tools, or a history that went another
                # way (a compaction, a message mid-turn): a fresh thread with all of it.
                await self._close_server()
                await self._ensure_thread(request, cancel)
                new_messages = request.messages
            else:
                new_messages = tuple(message for message in fresh if message.role != "assistant")
            assert self._thread_id is not None
            await self._rpc(
                "turn/start",
                {
                    "threadId": self._thread_id,
                    "cwd": str(self._workspace),
                    "input": [
                        {"type": "text", "text": _turn_text(new_messages)},
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
                },
                cancel=cancel,
            )
        self._messages_snapshot = request.messages
        streamed = False
        while True:
            message = await self._next_message(cancel)
            method = message.get("method")
            params = message.get("params")
            if not isinstance(method, str) or not isinstance(params, dict):
                continue
            event = cast("dict[str, object]", params)
            if method == "item/tool/call" and "id" in message:
                call_id = _as_str(event.get("callId")) or f"call_{uuid4().hex}"
                self._pending.append((message["id"], call_id))
                yield ToolCallReady(
                    call=tool_call(
                        {"name": event.get("tool"), "args": event.get("arguments")}, "call"
                    ).model_copy(update={"id": call_id})
                )
                yield Stop(reason="tool_use")
                return
            if method == "item/agentMessage/delta":
                delta = event.get("delta")
                if isinstance(delta, str) and delta:
                    streamed = True
                    yield TextDelta(text=delta)
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
                    raise ProviderError(
                        _failure(_as_dict(turn.get("error")), f"Codex turn failed: {status}")
                    )
                if not streamed:
                    items = turn.get("items")
                    for raw_item in cast("list[object]", items) if isinstance(items, list) else []:
                        item = _as_dict(raw_item)
                        if item is not None and item.get("type") == "agentMessage":
                            text = _as_str(item.get("text"))
                            if text:
                                yield TextDelta(text=text)
                yield Stop(reason="end_turn")
                return
            elif method == "error":
                nested = _as_dict(event.get("error")) or event
                raise ProviderError(_failure(nested, "Codex app server: turn failed"))


def _turn_text(messages: Sequence[LlmMessage]) -> str:
    """What a turn starts with: the new prompt as it is, or, for a thread that starts mid-way, the
    conversation so far and then the newest message."""
    if len(messages) == 1 and messages[0].role == "user":
        return messages[0].content
    earlier = [
        json.dumps(
            message.model_dump(mode="json", exclude_none=True, exclude={"images", "native"}),
            ensure_ascii=False,
        )
        for message in messages[:-1]
    ]
    last = messages[-1] if messages else None
    return (
        "The conversation so far, for context; your own earlier answers and the tools' results "
        "are in it:\n<conversation>\n"
        + "\n".join(earlier)
        + "\n</conversation>\n\n"
        + (
            last.content
            if last is not None and last.role == "user"
            else "Continue the conversation."
        )
    )
