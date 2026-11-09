"""An installed agent CLI as a model backend, with the CLI's own sign-in.

None of these CLIs takes Plural's tools as its own, so each call asks for a JSON answer of text
and tool calls, the way the Claude Code provider does, and reads it back from the CLI's output.
The CLI runs in an empty folder of its own, in its read-only mode where it has one, so that its
own tools, if the model reaches for them anyway, find nothing of the workspace.

A CLI is a subclass that says how to start it (`command`) and how to read one line of its
output (`parse`); starting, streaming, cancelling and reading the answer are shared here.
"""

import asyncio
import json
import os
import shutil
import tempfile
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Final, cast
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
from plural.agent.providers.cli.answer import TextFieldStream, parse_answer
from plural.agent.providers.preset import AgentCliAdapter
from plural.protocol.models import Usage

INSTRUCTIONS: Final = (
    "You are the model behind Plural, an agent that runs its own tools. Continue the "
    "conversation below. You have no tools of your own: do not run commands, read files or call "
    "any tool yourself. When a tool is needed, name it in tool_calls with its JSON arguments; "
    "Plural asks for approval, runs it and sends the result in a later message. Never claim a "
    "tool ran before its result appears.\n"
    "Reply with one JSON object and nothing else, no code fence:\n"
    '{"text": "<what you say to the user>", "tool_calls": [{"name": "<tool>", "args": {}}]}\n'
    "Leave tool_calls empty when no tool is needed."
)

# How long the CLI may stay quiet before the run is told it is still working.
HEARTBEAT_S: Final = 10.0


@dataclass(frozen=True, slots=True)
class Event:
    """What one line of a CLI's output says about the answer."""

    delta: str = ""
    # A whole message, which replaces what streamed before it.
    message: str | None = None
    usage: Usage | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class Call:
    argv: list[str]
    stdin: bytes | None = None


# The prompt line for CLIs that read the request itself from stdin.
ASK: Final = "Answer the request above as instructed."


def prompt_text(request: LlmRequest) -> str:
    """The whole request as one prompt: instructions, system prompt, tools, then each message."""
    tools = [tool.model_dump(mode="json") for tool in request.tools]
    parts = [
        INSTRUCTIONS,
        f"<system>\n{request.system}\n</system>",
        "<tools>\n" + json.dumps(tools, ensure_ascii=False) + "\n</tools>",
        "<conversation>",
    ]
    for message in request.messages:
        dumped = message.model_dump(mode="json", exclude_none=True, exclude={"images"})
        if message.images:
            dumped["images"] = f"{len(message.images)} image(s) not shown to this model"
        parts.append(json.dumps(dumped, ensure_ascii=False))
    parts.append("</conversation>")
    return "\n".join(parts)


def as_dict(value: object) -> dict[str, object] | None:
    return cast("dict[str, object]", value) if isinstance(value, dict) else None


def int_of(data: dict[str, object] | None, *keys: str) -> int:
    for key in keys:
        value = data.get(key) if data is not None else None
        if isinstance(value, int):
            return value
    return 0


class AgentCliProvider(ABC):
    adapter: ClassVar[AgentCliAdapter]
    label: ClassVar[str]
    binary: ClassVar[str]
    # How to install it and sign in, for the settings screen and error messages.
    install: ClassVar[str]
    login: ClassVar[str]

    def __init__(self, *, model: str = "", cli: str | None = None) -> None:
        path = cli or shutil.which(self.binary)
        if path is None:
            raise ProviderError(
                f"{self.label} is not installed: {self.install}, then {self.login}."
            )
        self._path = path
        self._model = model

    @abstractmethod
    def command(self, prompt: str, run_dir: Path) -> Call:
        """The arguments after the binary, and what goes to stdin, for one request."""

    @abstractmethod
    def parse(self, event: dict[str, object]) -> Event | None:
        """What one JSON line of the CLI's output says about the answer, if anything."""

    def model_flag(self, flag: str) -> list[str]:
        return [flag, self._model] if self._model else []

    async def stream(
        self, request: LlmRequest, *, cancel: asyncio.Event
    ) -> AsyncIterator[LlmEvent]:
        with tempfile.TemporaryDirectory(prefix="plural-cli-") as folder:
            run_dir = Path(folder)
            call = self.command(prompt_text(request), run_dir)
            async for event in self._run(request, call, run_dir, cancel):
                yield event

    async def _run(
        self, request: LlmRequest, call: Call, run_dir: Path, cancel: asyncio.Event
    ) -> AsyncIterator[LlmEvent]:
        try:
            process = await asyncio.create_subprocess_exec(
                self._path,
                *call.argv,
                cwd=run_dir,
                stdin=asyncio.subprocess.PIPE
                if call.stdin is not None
                else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=16 * 1024 * 1024,
                env={**os.environ, "NO_COLOR": "1", "CI": "1"},
            )
        except OSError as failure:
            raise ProviderError(f"Could not start {self.label}: {failure}") from failure
        assert process.stdout is not None
        assert process.stderr is not None
        if call.stdin is not None:
            assert process.stdin is not None
            process.stdin.write(call.stdin)
            await process.stdin.drain()
            process.stdin.close()
        stderr_reader = asyncio.create_task(process.stderr.read())
        stopping = asyncio.create_task(cancel.wait())
        text_stream = TextFieldStream()
        streamed = ""
        deltas = ""
        message: str | None = None
        loose: list[str] = []
        usage: Usage | None = None
        error: str | None = None
        try:
            while True:
                line_reader = asyncio.create_task(process.stdout.readline())
                while True:
                    done, _ = await asyncio.wait(
                        {line_reader, stopping},
                        timeout=HEARTBEAT_S,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if done:
                        break
                    yield ProviderActivity(source="waiting")
                if stopping in done:
                    line_reader.cancel()
                    await asyncio.gather(line_reader, return_exceptions=True)
                    return
                line = await line_reader
                if not line:
                    break
                yield ProviderActivity(source=self.adapter)
                try:
                    decoded: object = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    loose.append(line.decode(errors="replace"))
                    continue
                event = (
                    self.parse(cast("dict[str, object]", decoded))
                    if isinstance(decoded, dict)
                    else None
                )
                if event is None:
                    continue
                if event.delta:
                    deltas += event.delta
                    text = text_stream.feed(event.delta)
                    if text:
                        streamed += text
                        yield TextDelta(text=text)
                if event.message is not None:
                    message = event.message
                usage = event.usage or usage
                error = event.error or error
            await process.wait()
        finally:
            stopping.cancel()
            if process.returncode is None:
                process.kill()
                await process.wait()
            await asyncio.gather(stderr_reader, stopping, return_exceptions=True)
        if cancel.is_set():
            return
        raw = message if message is not None else deltas or "".join(loose)
        stderr = stderr_reader.result().decode(errors="replace").strip()
        if error or (process.returncode != 0 and not raw.strip()):
            detail = error or stderr[-300:] or f"exit code {process.returncode}"
            raise ProviderError(f"{self.label}: {detail}. If signed out: {self.login}.")
        answer = parse_answer(raw)
        text, calls = answer if answer is not None else (raw.strip(), [])
        remaining = (
            text[len(streamed) :] if text.startswith(streamed) else ("" if streamed else text)
        )
        if remaining:
            yield TextDelta(text=remaining)
        names = {tool.name for tool in request.tools}
        for name, args in calls:
            if name not in names:
                raise ProviderError(f"{self.label} requested an unavailable tool: {name}")
            yield ToolCallReady(
                call=ToolCallRequest(
                    id=f"toolu_{uuid4().hex}",
                    name=name,
                    args=cast("dict[str, JsonValue]", args),
                )
            )
        if usage is not None:
            yield UsageReport(usage=usage)
        yield Stop(reason="tool_use" if calls else "end_turn")
