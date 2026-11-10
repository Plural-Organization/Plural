import re
import zlib
from datetime import timedelta
from typing import Final

from plural.core.ports import Clock, IdGenerator
from plural.host.approval_registry import ApprovalRegistry
from plural.host.inbox import ApprovalNeeded, ChatAccepted, Inbox
from plural.protocol.commands import BriefingImport
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

PREVIEW_CHARS: Final = 600
SOURCE_CHARS: Final = 40
ANSWER_LIMIT_S: Final = 100.0


def label(text: str, fallback: str) -> str:
    """What a chat service says about itself, cut down to something safe to show and file."""
    cleaned = re.sub(r"[^\w .@#-]", " ", text)
    cleaned = " ".join(cleaned.split())[:SOURCE_CHARS].strip()
    return cleaned if cleaned and re.match(r"\w", cleaned) else fallback


class ChatDesk:
    """Puts what a chat service sent in front of the host and, if it is accepted, to the agent.
    The chat reaches us through the MCP gateway; see plural.host.mcp_link."""

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
