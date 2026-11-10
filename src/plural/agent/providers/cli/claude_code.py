"""Use the installed Claude Code CLI as a genuine, non-interactive model backend."""

import asyncio
import json
import os
from collections import OrderedDict
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from pydantic import JsonValue

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
from plural.agent.providers.cli.answer import TextFieldStream, tool_call
from plural.agent.providers.cli.base import CliProvider
from plural.protocol.models import Usage


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


def _input(
    request: LlmRequest, messages: Sequence[LlmMessage] | None = None, shown: int = 0
) -> bytes:
    """One stream-json user message: the instructions, the tools, then each message in turn.

    A session's first message carries the instructions, the tools and the whole conversation;
    each later one only the messages that came after it, since Claude Code keeps the rest. Each
    message is a block of its own, so a call repeats the blocks of the one before it from the start
    and the provider's prompt cache serves them. An image follows the message it belongs to;
    `shown` counts the images the session was already sent, so their labels go on.
    """
    content: list[dict[str, Any]] = []
    if messages is None:
        tools = [tool.model_dump(mode="json") for tool in request.tools]
        content = [
            {"type": "text", "text": INSTRUCTIONS},
            {"type": "text", "text": json.dumps({"tools": tools}, ensure_ascii=False)},
        ]
        messages = request.messages
    count = shown
    for message in messages:
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


class _Gone(Exception):
    """The Claude Code process ended before it answered."""


# How many conversations keep a Claude Code process of their own: the room's, and its sub-agents'.
MAX_SESSIONS = 4


@dataclass(slots=True)
class _Session:
    """A Claude Code process that keeps one conversation between calls.

    Starting `claude -p` costs about a second and a half before the model is even asked, on every
    call. A session pays that once: later calls send only the messages that came after the last
    one, and Claude Code keeps the rest of the conversation itself.
    """

    process: asyncio.subprocess.Process
    # The messages Claude Code holds, as the last request had them.
    sent: tuple[LlmMessage, ...] = ()
    images: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # The end of what Claude Code wrote to stderr, for an error message.
    errors: bytearray = field(default_factory=bytearray)
    reader: asyncio.Task[None] | None = None

    @property
    def alive(self) -> bool:
        return self.process.returncode is None

    async def close(self) -> None:
        if self.process.returncode is None:
            if self.process.stdin is not None:
                self.process.stdin.close()
            self.process.kill()
            await self.process.wait()
        if self.reader is not None:
            self.reader.cancel()
            await asyncio.gather(self.reader, return_exceptions=True)


def _key(request: LlmRequest) -> str:
    """A conversation's identity: its system prompt, its tools and its first message. Requests
    with the same key continue one another; a compaction, a sub-agent or a side question has a
    key of its own."""
    first = request.messages[0].model_dump_json(exclude={"images"}) if request.messages else ""
    tools = json.dumps([tool.model_dump(mode="json") for tool in request.tools])
    return sha256(f"{request.system}\0{tools}\0{first}".encode()).hexdigest()


class ClaudeCodeProvider(CliProvider):
    adapter = "claude_code"
    label = "Claude Code"
    binary = "claude"
    install = "npm install -g @anthropic-ai/claude-code"
    login = "claude auth login"
    models = (
        "claude-sonnet-5-5",
        "claude-opus-5-5",
        "claude-haiku-5-5",
        "claude-fable-5-1",
        "claude-sonnet-5",
        "claude-opus-5",
        "claude-fable-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "claude-opus-4-6",
        "claude-opus-4-5-20251101",
        "claude-haiku-4-5-20251001",
        "claude-sonnet-4-5-20250929",
    )
    hint = "Uses the installed Claude Code CLI; sign in with claude auth login"

    def __init__(self, *, model: str = "", workspace: Path, cli: str | None = None) -> None:
        super().__init__(model=model, workspace=workspace, cli=cli)
        self._window: int | None = None
        self._sessions: OrderedDict[str, _Session] = OrderedDict()

    async def close(self) -> None:
        sessions, self._sessions = list(self._sessions.values()), OrderedDict()
        await asyncio.gather(*(session.close() for session in sessions), return_exceptions=True)

    async def _start(self, request: LlmRequest) -> _Session:
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
        session = _Session(process)
        session.reader = asyncio.create_task(_drain(process, session.errors))
        return session

    async def _session(self, request: LlmRequest) -> tuple[_Session, bytes]:
        """The process for this request's conversation and what to send it: only the new
        messages when it already holds the ones before, or everything to a new process."""
        key = _key(request)
        session = self._sessions.get(key)
        if session is not None:
            self._sessions.move_to_end(key)
            held = len(session.sent)
            fresh = request.messages[held:]
            if (
                session.alive
                and request.messages[:held] == session.sent
                and any(message.role != "assistant" for message in fresh)
            ):
                # The model's own answers are in Claude Code's history already.
                new = [message for message in fresh if message.role != "assistant"]
                return session, _input(request, new, session.images)
            del self._sessions[key]
            await session.close()
        session = await self._start(request)
        self._sessions[key] = session
        while len(self._sessions) > MAX_SESSIONS:
            _, oldest = self._sessions.popitem(last=False)
            await oldest.close()
        return session, _input(request)

    async def _forget(self, session: _Session) -> None:
        for key, held in list(self._sessions.items()):
            if held is session:
                del self._sessions[key]
        await session.close()

    async def context_window(self) -> int | None:
        """The window Claude Code reported with its last answer."""
        return self._window

    async def stream(
        self, request: LlmRequest, *, cancel: asyncio.Event
    ) -> AsyncIterator[LlmEvent]:
        session, payload = await self._session(request)
        reused = bool(session.sent)
        async with session.lock:
            finished = False
            said = False
            try:
                async for event in self._turn(request, session, payload, cancel):
                    said = True
                    yield event
                finished = True
            except _Gone:
                if not reused or said:
                    raise ProviderError(
                        f"Claude Code stopped: {_tail(session) or 'check claude auth login'}"
                    ) from None
            finally:
                if not finished or cancel.is_set():
                    # A turn cut short leaves the process mid-answer: it starts over next time.
                    await self._forget(session)
        if not finished and not cancel.is_set():
            # The process it kept had ended in the meantime: one fresh start with everything.
            fresh, payload = await self._session(request)
            async with fresh.lock:
                finished = False
                try:
                    async for event in self._turn(request, fresh, payload, cancel):
                        yield event
                    finished = True
                except _Gone:
                    raise ProviderError(
                        f"Claude Code stopped: {_tail(fresh) or 'check claude auth login'}"
                    ) from None
                finally:
                    if not finished or cancel.is_set():
                        await self._forget(fresh)

    async def _turn(
        self, request: LlmRequest, session: _Session, payload: bytes, cancel: asyncio.Event
    ) -> AsyncIterator[LlmEvent]:
        process = session.process
        assert process.stdin is not None
        assert process.stdout is not None
        try:
            process.stdin.write(payload)
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as error:
            raise _Gone from error
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
                    # The turn is over; the process waits for the next one.
                    result = event
                    break
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
                        await self._forget(session)
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
        finally:
            stopping.cancel()
            await asyncio.gather(stopping, return_exceptions=True)
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
        if result is None:
            # The process ended: before saying anything it is worth one fresh start.
            raise _Gone
        if result.get("is_error") is True:
            await self._forget(session)
            result_detail = result.get("result")
            detail = (result_detail if isinstance(result_detail, str) else _tail(session))[:300]
            raise ProviderError(f"Claude Code: {detail or 'run claude auth login'}")
        decoded_answer = result.get("structured_output")
        if not isinstance(decoded_answer, dict):
            await self._forget(session)
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
            # A tool Plural lacks or bad arguments come back to the model as the call's error.
            yield ToolCallReady(call=tool_call(raw_call))
        fresh = request.messages[len(session.sent) :]
        session.images += sum(len(message.images) for message in fresh)
        session.sent = request.messages
        self._window = _window(result) or self._window
        # A result sums every request Claude Code made for this answer; the last one holds the
        # conversation as it now stands.
        usage = _usage(result.get("usage"))
        if usage is not None:
            yield UsageReport(usage=usage, last=_last_usage(result.get("usage")))
        yield Stop(reason="tool_use" if calls else "end_turn")


async def _drain(process: asyncio.subprocess.Process, kept: bytearray) -> None:
    """Read stderr as it comes, keeping its end: a full pipe would stall the process."""
    assert process.stderr is not None
    while chunk := await process.stderr.read(4096):
        kept.extend(chunk)
        del kept[:-4000]


def _tail(session: _Session) -> str:
    return session.errors.decode(errors="replace").strip()[-300:]
