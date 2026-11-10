import asyncio
import os
import shutil
import tempfile
from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from plural.agent.providers.base import LlmEvent, LlmMessage, LlmRequest, Stop
from plural.agent.providers.cli.prompt_cli import (
    INSTRUCTIONS,
    Call,
    Event,
    as_dict,
    continuation_text,
    conversation_key,
    int_of,
    prompt_text,
)
from plural.agent.providers.cli.stream_json import ClaudeStreamCli
from plural.protocol.models import Usage

# Grok Build's own tools. Plural brings its own, so each would only cost tokens on every request
# and tempt the model away from the JSON answer. An unknown name is ignored, not an error.
OWN_TOOLS = (
    "ask_user_question",
    "enter_plan_mode",
    "exit_plan_mode",
    "get_command_or_subagent_output",
    "grep",
    "image_edit",
    "image_gen",
    "image_to_video",
    "kill_command_or_subagent",
    "list_dir",
    "monitor",
    "read_file",
    "reference_to_video",
    "run_terminal_command",
    "scheduler_create",
    "scheduler_delete",
    "scheduler_list",
    "search_replace",
    "search_tool",
    "send_feedback",
    "todo_write",
    "use_tool",
    "workflow",
    "write",
)

# What Grok Build brings into every request on its own, switched off: skills, rules, MCP servers,
# hooks and agents it imports from Claude Code, Cursor and Codex, its server-side search (it would
# search X for a file name), memory across sessions, and MCP servers xAI manages. On a machine with
# a few of those, a request went from 19k prompt tokens to 5.6k with them off.
QUIET = {
    "GROK_BACKEND_SEARCH": "0",
    "GROK_MEMORY": "0",
    "GROK_MANAGED_MCPS_ENABLED": "0",
    **{
        f"GROK_{source}_{part}_ENABLED": "0"
        for source in ("CLAUDE", "CURSOR", "CODEX")
        for part in ("SKILLS", "RULES", "MCPS", "AGENTS", "HOOKS")
    },
}

# How many conversations keep a Grok session: the room's, and its sub-agents'.
MAX_SESSIONS = 4


@dataclass(slots=True)
class _Session:
    """A Grok Build session that keeps one conversation between calls. A new session pays for
    its whole prompt; a resumed one reads it from xAI's cache and sends only what is new."""

    id: str
    sent: tuple[LlmMessage, ...] = ()


class GrokCliProvider(ClaudeStreamCli):
    adapter = "grok_cli"
    label = "Grok CLI"
    binary = "grok"
    install = "see x.ai/cli"
    login = "grok login"
    models = ("grok-4.7", "grok-4.7-build-fast", "grok-4.6", "grok-4.5")

    def __init__(self, *, model: str = "", workspace: Path, cli: str | None = None) -> None:
        super().__init__(model=model, workspace=workspace, cli=cli)
        self._sessions: OrderedDict[str, _Session] = OrderedDict()
        self._lock = asyncio.Lock()
        # One folder for every call: Grok keeps its sessions by the folder they ran in.
        self._home = Path(tempfile.mkdtemp(prefix="plural-grok-"))
        # Grok's own home folder, empty but for what it writes: the user's Grok skills, plugins
        # and settings stay out of Plural's requests. Its sign-in is read where it lives.
        own = Path(os.environ.get("GROK_HOME") or os.path.expanduser("~/.grok"))
        self._grok_home = self._home / "grok-home"
        self._grok_home.mkdir()
        self._auth = os.environ.get("GROK_AUTH_PATH") or str(own / "auth.json")
        # The session the next command starts or resumes.
        self._session: tuple[str, bool] | None = None

    async def close(self) -> None:
        self._sessions.clear()
        shutil.rmtree(self._home, ignore_errors=True)

    async def stream(
        self, request: LlmRequest, *, cancel: asyncio.Event
    ) -> AsyncIterator[LlmEvent]:
        async with self._lock:
            key = conversation_key(request)
            session = self._sessions.pop(key, None)
            held = len(session.sent) if session is not None else 0
            new = [message for message in request.messages[held:] if message.role != "assistant"]
            if session is not None and request.messages[:held] == session.sent and new:
                prompt, resumed = continuation_text(new), True
            else:
                session, prompt, resumed = _Session(uuid4().hex), prompt_text(request), False
            self._session = (_uuid(session.id), resumed)
            call = self.command(prompt, self._home)
            finished = False
            async for event in self._run(request, call, self._home, cancel):
                if isinstance(event, Stop):
                    finished = True
                yield event
            if finished and not cancel.is_set():
                session.sent = request.messages
                self._sessions[key] = session
                while len(self._sessions) > MAX_SESSIONS:
                    self._sessions.popitem(last=False)

    def environment(self) -> dict[str, str]:
        return {**QUIET, "GROK_HOME": str(self._grok_home), "GROK_AUTH_PATH": self._auth}

    def command(self, prompt: str, run_dir: Path) -> Call:
        # A long conversation would not fit in one argument, so it goes in a file.
        request = run_dir / f"request-{uuid4().hex}.md"
        request.write_text(prompt, encoding="utf-8")
        session: list[str] = []
        if self._session is not None:
            session_id, resumed = self._session
            session = ["--resume" if resumed else "--session-id", session_id]
        return Call(
            [
                *self.model_flag("-m"),
                "--prompt-file",
                str(request),
                "--output-format",
                "streaming-json",
                "--system-prompt-override",
                INSTRUCTIONS,
                # Not plan mode: it tells the model to write its plan to a file in Grok's own
                # folder, which it then does with Plural's write tool, and to stop at a plan.
                # Grok's own tools are off, so the model can only answer.
                "--no-subagents",
                "--disable-web-search",
                "--disallowed-tools",
                ",".join(OWN_TOOLS),
                "--no-memory",
                *session,
            ]
        )

    def parse(self, event: dict[str, object]) -> Event | None:
        """Grok Build's own stream: the answer's text in pieces, each request's usage on its
        own, and its tool calls. Its input tokens leave out the part read from the cache."""
        kind = event.get("type")
        if kind == "text":
            data = event.get("data")
            return Event(delta=data) if isinstance(data, str) else None
        if kind == "tool_call":
            # Grok reached for a tool of its own; what it wrote before was not the answer.
            return Event(restart=True)
        if kind == "usage":
            usage = as_dict(event.get("usage"))
            if usage is None:
                return None
            return Event(
                request=Usage(
                    input_tokens=int_of(usage, "input_tokens"),
                    output_tokens=int_of(usage, "output_tokens"),
                    cache_read_tokens=int_of(usage, "cache_read_input_tokens"),
                    cache_write_tokens=int_of(usage, "cache_creation_input_tokens"),
                )
            )
        return super().parse(event)


def _uuid(hex_id: str) -> str:
    return f"{hex_id[:8]}-{hex_id[8:12]}-{hex_id[12:16]}-{hex_id[16:20]}-{hex_id[20:]}"
