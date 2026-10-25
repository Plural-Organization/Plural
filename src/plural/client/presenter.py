from dataclasses import dataclass

from plural.client.projection import Projection
from plural.protocol.events import (
    ApprovalRequested,
    ApprovalResolved,
    AttachmentAdded,
    ContextCompacted,
    ErrorRaised,
    Event,
    InviteCreated,
    MessageEnded,
    ParticipantJoined,
    ParticipantLeft,
    ParticipantRevoked,
    ParticipantRoleChanged,
    PolicyRuleAdded,
    PolicyRuleRemoved,
    PromptAccepted,
    ProposalApproved,
    ProposalCreated,
    ProposalRejected,
    RunEnded,
    RunStarted,
    ToolEnded,
    ToolStarted,
)
from plural.protocol.models import (
    EntryKind,
    Origin,
    Participant,
    PolicyRuleView,
    SessionState,
    TranscriptEntry,
)

PREVIEW_LINES = 12


@dataclass(frozen=True, slots=True)
class Line:
    style: str
    text: str


def history(state: SessionState) -> list[Line]:
    return [line for entry in state.transcript for line in _entry(entry, state)]


def _entry(entry: TranscriptEntry, state: SessionState) -> list[Line]:
    match entry.kind:
        case EntryKind.PROMPT:
            return [Line("bold", f"{_name(state, entry.author_id)} › {entry.text}")]
        case EntryKind.ASSISTANT:
            return [Line("", entry.text)] if entry.text else []
        case EntryKind.TOOL:
            if entry.tool is None:
                return []
            mark = {True: "✓", False: "✗", None: "…"}[entry.ok]
            style = {True: "cyan", False: "red", None: "cyan"}[entry.ok]
            lines = [Line(style, f"⚙ {entry.tool.name} {entry.tool.subject} {mark}")]
            if entry.output:
                lines.append(Line("green" if entry.ok else "red", _preview(entry.output)))
            return lines
        case EntryKind.COMPACTION:
            return [Line("dim", f"⟲ {entry.text}")]


def _preview(output: str) -> str:
    return "\n".join(output.splitlines()[:PREVIEW_LINES])


def label(state: SessionState, participant: Participant) -> str:
    twins = sum(1 for other in state.participants.values() if other.name == participant.name)
    return participant.name if twins < 2 else f"{participant.name} #{participant.id[-4:]}"


def _name(state: SessionState, participant_id: str | None) -> str:
    participant = state.participants.get(participant_id or "")
    return label(state, participant) if participant else participant_id or "system"


def rule_line(rule: PolicyRuleView) -> str:
    return f"{rule.action:<5} {rule.tool} {rule.pattern}"


def live(projection: Projection) -> str:
    streamed = "".join(projection.streaming.values())
    state = projection.state
    if streamed:
        return streamed
    if state.run is None:
        return ""
    if state.approvals:
        return "… waiting for host approval"
    last = state.transcript[-1] if state.transcript else None
    if last is not None and last.tool is not None and last.ok is None:
        return f"… running {last.tool.name}"
    if projection.reasoning:
        return f"… thinking ({projection.reasoning} chars)"
    return "… waiting for the model"


def describe(event: Event, state: SessionState) -> Line | None:
    def name(participant_id: str | None) -> str:
        return _name(state, participant_id)

    match event:
        case ParticipantJoined(participant=participant):
            return Line("dim", f"→ {label(state, participant)} joined as {participant.role}")
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
            return Line("green" if ok else "red", _preview(output))
        case ApprovalRequested(approval=approval):
            call = approval.call
            return Line("magenta", f"! approval needed: {call.name} {call.subject} [{call.risk}]")
        case ApprovalResolved(decision=decision, resolved_by=resolved_by):
            suffix = "timeout" if resolved_by is None else name(resolved_by)
            return Line("magenta", f"! approval {decision} ({suffix})")
        case ContextCompacted(tokens_before=tokens_before):
            return Line("dim", f"⟲ context compacted ({tokens_before} tokens summarized)")
        case PolicyRuleAdded(rule=rule):
            return Line("magenta", f"policy + {rule_line(rule)}  [{rule.id}]")
        case PolicyRuleRemoved(rule_id=rule_id):
            return Line("magenta", f"policy - {rule_id}")
        case AttachmentAdded(attachment=attachment):
            return Line("dim", f"📎 {name(attachment.owner_id)} attached {attachment.name}")
        case InviteCreated(link=link, role=role):
            return Line("green", f"invite ({role}): {link}")
        case ErrorRaised(message=message):
            return Line("red", message)
        case _:
            return None
