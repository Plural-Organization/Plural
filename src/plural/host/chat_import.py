import json
import re
import secrets
import zlib
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any, Final, cast

import structlog
from pydantic import ValidationError

from plural import __version__
from plural.core.ports import Clock, IdGenerator
from plural.host.approval_registry import ApprovalRegistry
from plural.host.inbox import ApprovalNeeded, ChatAccepted, Inbox
from plural.protocol.commands import MAX_BRIEFING_CHARS, BriefingImport
from plural.protocol.models import (
    HOST_PARTICIPANT_ID,
    ApprovalDecision,
    ApprovalView,
    Origin,
    Provenance,
    Role,
    ToolCallView,
    ToolRisk,
)
from plural.protocol.relay import CallReply, CallRequest

log = structlog.get_logger(__name__)

TOOL: Final = "add_data_to_session"
PROTOCOLS: Final = ("2025-06-18", "2025-03-26", "2024-11-05")
PREVIEW_CHARS: Final = 600
SOURCE_CHARS: Final = 40
ANSWER_LIMIT_S: Final = 100.0

DESCRIPTION: Final = (
    "Send the context of this conversation to the Plural session it is connected to, so the people "
    "there can carry on the work. Write it as a hand-over note and pass it as `context`: the goal, "
    "what was decided, where things stand, what is left, the files, commands and names that "
    "matter, and the last few messages nearly word for word. Leave out passwords, keys and tokens. "
    "Keep it under 15000 characters. The host of the session sees it first and may decline."
)

SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "context": {
            "type": "string",
            "description": "The hand-over note, as plain text or markdown.",
            "minLength": 1,
            "maxLength": MAX_BRIEFING_CHARS,
        },
        "title": {
            "type": "string",
            "description": "A short title for the topic of the conversation.",
            "maxLength": 80,
        },
        "source": {
            "type": "string",
            "description": "Which assistant sends this, for example Claude or ChatGPT.",
            "maxLength": SOURCE_CHARS,
        },
    },
    "required": ["context"],
    "additionalProperties": False,
}

# What a call may ask the host to add: where from, what it is about, and the text.
Offer = Callable[[str, str, str], Awaitable[bool]]


def _label(text: str, fallback: str) -> str:
    cleaned = re.sub(r"[^\w .@#-]", " ", text)
    cleaned = " ".join(cleaned.split())[:SOURCE_CHARS].strip()
    return cleaned if cleaned and re.match(r"\w", cleaned) else fallback


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _text(message: str, *, error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": error}


class ChatImport:
    """The import link: a small MCP server a chat service (Claude, ChatGPT, Grok) is connected to.
    It offers one tool, `add_data_to_session`. What comes through is held for the host, and only
    goes to the agent's notes when the host agrees."""

    def __init__(self, offer: Offer, *, token: str | None = None) -> None:
        self._offer = offer
        self.token = token or secrets.token_urlsafe(24)

    async def handle(self, raw: str) -> str:
        """Answer one request the relay passed on, as a CallReply in JSON."""
        try:
            call = CallRequest.model_validate_json(raw)
        except ValidationError:
            return CallReply(status=400).model_dump_json()
        if not secrets.compare_digest(call.token, self.token):
            return CallReply(status=404).model_dump_json()
        try:
            message = json.loads(call.body)
        except ValueError:
            reply = _error(None, -32700, "parse error")
            return CallReply(status=400, body=json.dumps(reply)).model_dump_json()
        items = cast(list[Any], message) if isinstance(message, list) else [message]
        answers = [answer for item in items if (answer := await self._one(item)) is not None]
        if not answers:
            return CallReply(status=202).model_dump_json()
        body = answers[0] if not isinstance(message, list) else answers
        return CallReply(status=200, body=json.dumps(body)).model_dump_json()

    async def _one(self, item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return _error(None, -32600, "invalid request")
        request = cast(dict[str, Any], item)
        method = request.get("method")
        request_id = request.get("id")
        if "id" not in request:
            return None
        raw_params = request.get("params")
        params = cast(dict[str, Any], raw_params) if isinstance(raw_params, dict) else {}
        match method:
            case "initialize":
                wanted = params.get("protocolVersion")
                version = wanted if wanted in PROTOCOLS else PROTOCOLS[0]
                return _result(
                    request_id,
                    {
                        "protocolVersion": version,
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "plural", "version": __version__},
                    },
                )
            case "ping":
                return _result(request_id, {})
            case "tools/list":
                tool = {"name": TOOL, "description": DESCRIPTION, "inputSchema": SCHEMA}
                return _result(request_id, {"tools": [tool]})
            case "tools/call":
                return _result(request_id, await self._call(params))
            case _:
                return _error(request_id, -32601, "method not found")

    async def _call(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("name") != TOOL:
            return _text(f"there is no tool {params.get('name')!r}", error=True)
        raw_arguments = params.get("arguments")
        arguments = cast(dict[str, Any], raw_arguments) if isinstance(raw_arguments, dict) else {}
        context = arguments.get("context")
        if not isinstance(context, str) or not context.strip():
            return _text("`context` is missing: pass the hand-over note as text", error=True)
        if len(context) > MAX_BRIEFING_CHARS:
            return _text(
                f"the note is {len(context)} characters and the limit is {MAX_BRIEFING_CHARS}. "
                "Write a shorter one and call the tool again",
                error=True,
            )
        source = _label(str(arguments.get("source") or ""), "Chat")
        title = _label(str(arguments.get("title") or ""), "untitled")
        try:
            accepted = await self._offer(source, title, context.strip())
        except Exception:
            log.exception("chat_import.failed")
            return _text("the host could not take it", error=True)
        if accepted:
            return _text("Added to the Plural session. Its agent will read it.")
        return _text("The host did not accept it, so nothing was added.", error=True)


class ChatDesk:
    """Puts what a chat service sent in front of the host and, if it is accepted, to the agent."""

    def __init__(
        self,
        *,
        inbox: Inbox,
        registry: ApprovalRegistry,
        ids: IdGenerator,
        clock: Clock,
        timeout_s: float,
    ) -> None:
        self._inbox = inbox
        self._registry = registry
        self._ids = ids
        self._clock = clock
        self._timeout = timedelta(seconds=min(timeout_s, ANSWER_LIMIT_S))

    async def offer(self, source: str, title: str, text: str) -> bool:
        call = ToolCallView(
            id=self._ids.new("tc_"),
            name="import_chat",
            risk=ToolRisk.WRITE,
            subject=f"{source}: {title}",
            args={
                "from": source,
                "title": title,
                "characters": len(text),
                "preview": text[:PREVIEW_CHARS],
            },
        )
        approval = ApprovalView(
            id=self._ids.new("ap_"),
            call=call,
            provenance=Provenance(
                initiator_id=HOST_PARTICIPANT_ID, initiator_role=Role.HOST, origin=Origin.DIRECT
            ),
            timeout_at=self._clock.now() + self._timeout,
            warnings=(
                f"{source} sends this through your import link. It goes to the agent's notes "
                "as background, never as instructions.",
            ),
        )
        waiter = self._registry.open(approval.id)
        self._inbox.put(ApprovalNeeded(approval))
        try:
            answer = await waiter
        finally:
            self._registry.discard(approval.id)
        if answer not in (ApprovalDecision.ONCE, ApprovalDecision.ALWAYS):
            return False
        command = BriefingImport(
            source=f"{source} chat {title}"[:80],
            as_of_seq=zlib.crc32(text.encode()),
            text=text,
        )
        self._inbox.put(ChatAccepted(command))
        return True
