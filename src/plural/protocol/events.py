from datetime import datetime
from typing import Annotated, ClassVar, Literal

from pydantic import Field

from plural.protocol.envelope import ErrorCode
from plural.protocol.models import (
    ApprovalDecision,
    ApprovalView,
    AttachmentMeta,
    Delivery,
    Model,
    Participant,
    ProposalView,
    Provenance,
    Role,
    RunEndReason,
    SessionState,
    ToolCallView,
    Usage,
)


class EventBase(Model):
    durable: ClassVar[bool] = True


class TransientEvent(EventBase):
    durable: ClassVar[bool] = False


class ParticipantJoined(EventBase):
    type: Literal["participant.joined"] = "participant.joined"
    participant: Participant


class ParticipantLeft(EventBase):
    type: Literal["participant.left"] = "participant.left"
    participant_id: str


class ParticipantRoleChanged(EventBase):
    type: Literal["participant.role_changed"] = "participant.role_changed"
    participant_id: str
    role: Role


class ParticipantRevoked(EventBase):
    type: Literal["participant.revoked"] = "participant.revoked"
    participant_id: str


class ProposalCreated(EventBase):
    type: Literal["proposal.created"] = "proposal.created"
    proposal: ProposalView


class ProposalApproved(EventBase):
    type: Literal["proposal.approved"] = "proposal.approved"
    proposal_id: str
    decided_by: str
    text: str


class ProposalRejected(EventBase):
    type: Literal["proposal.rejected"] = "proposal.rejected"
    proposal_id: str
    decided_by: str


class PromptAccepted(EventBase):
    type: Literal["prompt.accepted"] = "prompt.accepted"
    prompt_id: str
    author_id: str
    text: str
    delivery: Delivery
    provenance: Provenance
    attachments: tuple[str, ...] = ()


class RunStarted(EventBase):
    type: Literal["run.started"] = "run.started"
    run_id: str
    prompt_id: str
    provenance: Provenance


class RunEnded(EventBase):
    type: Literal["run.ended"] = "run.ended"
    run_id: str
    reason: RunEndReason
    usage: Usage = Usage()
    error: str | None = None


class MessageStarted(EventBase):
    type: Literal["message.started"] = "message.started"
    run_id: str
    message_id: str


class MessageDelta(TransientEvent):
    type: Literal["message.delta"] = "message.delta"
    message_id: str
    text: str
    thinking: bool = False


class MessageEnded(EventBase):
    type: Literal["message.ended"] = "message.ended"
    run_id: str
    message_id: str
    text: str
    thinking: str = ""


class ToolStarted(EventBase):
    type: Literal["tool.started"] = "tool.started"
    run_id: str
    call: ToolCallView


class ToolOutput(TransientEvent):
    type: Literal["tool.output"] = "tool.output"
    call_id: str
    chunk: str


class ToolEnded(EventBase):
    type: Literal["tool.ended"] = "tool.ended"
    run_id: str
    call_id: str
    ok: bool
    output: str
    diff: str | None = None


class ApprovalRequested(EventBase):
    type: Literal["approval.requested"] = "approval.requested"
    approval: ApprovalView


class ApprovalResolved(EventBase):
    type: Literal["approval.resolved"] = "approval.resolved"
    approval_id: str
    decision: ApprovalDecision
    resolved_by: str | None = None


class AttachmentAdded(EventBase):
    type: Literal["attachment.added"] = "attachment.added"
    attachment: AttachmentMeta


class SessionWelcome(TransientEvent):
    type: Literal["session.welcome"] = "session.welcome"
    room: str
    token: str
    participant: Participant


class SessionSnapshot(TransientEvent):
    type: Literal["session.snapshot"] = "session.snapshot"
    state: SessionState
    streaming: dict[str, str] = Field(default_factory=dict[str, str])


class InviteCreated(TransientEvent):
    type: Literal["invite.created"] = "invite.created"
    code: str
    role: Role
    expires_at: datetime
    link: str


class ErrorRaised(TransientEvent):
    type: Literal["error"] = "error"
    code: ErrorCode
    message: str


Event = Annotated[
    ParticipantJoined
    | ParticipantLeft
    | ParticipantRoleChanged
    | ParticipantRevoked
    | ProposalCreated
    | ProposalApproved
    | ProposalRejected
    | PromptAccepted
    | RunStarted
    | RunEnded
    | MessageStarted
    | MessageDelta
    | MessageEnded
    | ToolStarted
    | ToolOutput
    | ToolEnded
    | ApprovalRequested
    | ApprovalResolved
    | AttachmentAdded
    | SessionWelcome
    | SessionSnapshot
    | InviteCreated
    | ErrorRaised,
    Field(discriminator="type"),
]


class EventRecord(Model):
    seq: int
    id: str
    ts: datetime
    actor_id: str | None
    event: Event
