from dataclasses import dataclass

from plural.protocol.events import (
    ApprovalRequested,
    ApprovalResolved,
    AttachmentAdded,
    ErrorRaised,
    Event,
    InviteCreated,
    MessageEnded,
    ParticipantJoined,
    ParticipantLeft,
    ParticipantRevoked,
    ParticipantRoleChanged,
    PromptAccepted,
    ProposalApproved,
    ProposalCreated,
    ProposalRejected,
    RunEnded,
    RunStarted,
    ToolEnded,
    ToolStarted,
)
from plural.protocol.models import Origin, SessionState

PREVIEW_LINES = 12


@dataclass(frozen=True, slots=True)
class Line:
    style: str
    text: str


def describe(event: Event, state: SessionState) -> Line | None:
    def name(participant_id: str | None) -> str:
        participant = state.participants.get(participant_id or "")
        return participant.name if participant else participant_id or "system"

    match event:
        case ParticipantJoined(participant=participant):
            return Line("dim", f"→ {participant.name} joined as {participant.role}")
        case ParticipantLeft(participant_id=participant_id):
            return Line("dim", f"← {name(participant_id)} left")
        case ParticipantRoleChanged(participant_id=participant_id, role=role):
            return Line("dim", f"{name(participant_id)} is now {role}")
        case ParticipantRevoked(participant_id=participant_id):
            return Line("red", f"✗ access revoked for {participant_id}")
        case ProposalCreated(proposal=proposal):
            return Line("yellow", f"? {name(proposal.author_id)} proposes: {proposal.text}")
        case ProposalApproved(text=text):
            return Line("green", f"✓ proposal approved: {text}")
        case ProposalRejected():
            return Line("red", "✗ proposal rejected")
        case PromptAccepted(author_id=author_id, text=text, provenance=provenance):
            via = " (via proposal)" if provenance.origin is Origin.PROPOSAL else ""
            return Line("bold", f"{name(author_id)}{via} › {text}")
        case RunStarted():
            return Line("dim", "agent started")
        case RunEnded(reason=reason, error=error):
            return Line("dim", f"agent finished: {reason}" + (f" ({error})" if error else ""))
        case MessageEnded(text=text) if text:
            return Line("", text)
        case ToolStarted(call=call):
            return Line("cyan", f"⚙ {call.name} {call.subject}".rstrip())
        case ToolEnded(ok=ok, output=output):
            preview = "\n".join(output.splitlines()[:PREVIEW_LINES])
            return Line("green" if ok else "red", preview)
        case ApprovalRequested(approval=approval):
            call = approval.call
            return Line("magenta", f"! approval needed: {call.name} {call.subject} [{call.risk}]")
        case ApprovalResolved(decision=decision, resolved_by=resolved_by):
            suffix = "timeout" if resolved_by is None else name(resolved_by)
            return Line("magenta", f"! approval {decision} ({suffix})")
        case AttachmentAdded(attachment=attachment):
            return Line("dim", f"📎 {name(attachment.owner_id)} attached {attachment.name}")
        case InviteCreated(link=link, role=role):
            return Line("green", f"invite ({role}): {link}")
        case ErrorRaised(message=message):
            return Line("red", message)
        case _:
            return None
