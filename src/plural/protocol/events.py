from datetime import datetime
from typing import Annotated, ClassVar, Literal

from pydantic import Field

from plural.protocol.envelope import ErrorCode
from plural.protocol.models import (
    AccessDecision,
    AccessRequestView,
    AdmissionMode,
    AgentView,
    ApprovalDecision,
    ApprovalView,
    AskKind,
    AttachmentMeta,
    BoardCursor,
    BoardStroke,
    BriefingDecision,
    BriefingImportView,
    BriefingRequestView,
    BriefingSharing,
    ContextView,
    Delivery,
    DequeueReason,
    JoinDecision,
    JoinRequestView,
    McpServerView,
    Model,
    Participant,
    PermissionMode,
    PluginCommandView,
    PluginView,
    PolicyRuleView,
    PromptMode,
    ProposalView,
    Provenance,
    Role,
    RunEndReason,
    SessionState,
    SkillHit,
    SkillView,
    TextSelection,
    ToolCallView,
    Usage,
    UsageLine,
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


class PromptModeChanged(EventBase):
    type: Literal["session.prompt_mode_changed"] = "session.prompt_mode_changed"
    mode: PromptMode


class PermissionModeChanged(EventBase):
    type: Literal["session.permission_mode_changed"] = "session.permission_mode_changed"
    mode: PermissionMode


class SkillsChanged(EventBase):
    type: Literal["skills.changed"] = "skills.changed"
    skills: tuple[SkillView, ...]
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()


class SkillsFound(TransientEvent):
    type: Literal["skills.found"] = "skills.found"
    query: str
    hits: tuple[SkillHit, ...]


class PluginContextAdded(EventBase):
    """A plugin's before_run hook gave the agent context ahead of the run's prompt."""

    type: Literal["plugin.context"] = "plugin.context"
    run_id: str
    plugin: str
    text: str


class PluginLineSet(EventBase):
    """A plugin's status line changed; empty text removes it."""

    type: Literal["plugin.line"] = "plugin.line"
    plugin: str
    text: str


class PluginAsked(TransientEvent):
    """A plugin command asks whoever ran it a question. Only they get it; it is not logged."""

    type: Literal["plugin.asked"] = "plugin.asked"
    ask_id: str
    command: str
    kind: AskKind
    title: str
    options: tuple[str, ...] = ()
    default: str = ""


class PluginNotified(TransientEvent):
    """A short toast from a plugin command for the person who ran it."""

    type: Literal["plugin.notified"] = "plugin.notified"
    command: str
    text: str


class PluginShown(TransientEvent):
    """What a plugin command shows the person who ran it, and nobody else. It is not logged."""

    type: Literal["plugin.shown"] = "plugin.shown"
    command: str
    title: str
    text: str


class AgentChanged(EventBase):
    type: Literal["agent.changed"] = "agent.changed"
    agent: str
    fast: str = ""


class AdmissionChanged(EventBase):
    type: Literal["link.admission_changed"] = "link.admission_changed"
    mode: AdmissionMode


class JoinRequested(EventBase):
    type: Literal["join.requested"] = "join.requested"
    request: JoinRequestView


class JoinResolved(EventBase):
    type: Literal["join.resolved"] = "join.resolved"
    request_id: str
    decision: JoinDecision
    decided_by: str | None = None


class AccessRequested(EventBase):
    type: Literal["access.requested"] = "access.requested"
    request: AccessRequestView


class AccessResolved(EventBase):
    type: Literal["access.resolved"] = "access.resolved"
    participant_id: str
    decision: AccessDecision
    decided_by: str | None = None


class BriefingRequested(EventBase):
    type: Literal["briefing.requested"] = "briefing.requested"
    request: BriefingRequestView


class BriefingResolved(EventBase):
    type: Literal["briefing.resolved"] = "briefing.resolved"
    request_id: str
    participant_id: str
    decision: BriefingDecision
    decided_by: str | None = None


class BriefingDelivered(EventBase):
    type: Literal["briefing.delivered"] = "briefing.delivered"
    request_id: str
    to: str
    text: str = ""
    as_of_seq: int = 0
    update: bool = False
    error: str | None = None


class BriefingSharingChanged(EventBase):
    type: Literal["briefing.sharing_changed"] = "briefing.sharing_changed"
    mode: BriefingSharing


class BriefingImported(EventBase):
    type: Literal["briefing.imported"] = "briefing.imported"
    item: BriefingImportView
    text: str


class JoinPending(TransientEvent):
    type: Literal["session.pending"] = "session.pending"
    waiting: int = 1


class JoinRefused(TransientEvent):
    type: Literal["session.refused"] = "session.refused"
    reason: str


class PromptDequeued(EventBase):
    type: Literal["prompt.dequeued"] = "prompt.dequeued"
    prompt_id: str
    reason: DequeueReason


class ParticipantTyping(TransientEvent):
    type: Literal["participant.typing"] = "participant.typing"
    participant_id: str
    typing: bool


class ParticipantSelected(TransientEvent):
    type: Literal["participant.selected"] = "participant.selected"
    participant_id: str
    selection: TextSelection | None


class ParticipantCursor(TransientEvent):
    type: Literal["participant.cursor"] = "participant.cursor"
    participant_id: str
    cursor: BoardCursor | None


class BoardOpened(EventBase):
    type: Literal["board.opened"] = "board.opened"
    open: bool
    by: str


class BoardStroked(EventBase):
    type: Literal["board.stroked"] = "board.stroked"
    stroke: BoardStroke


class BoardMoved(EventBase):
    type: Literal["board.moved"] = "board.moved"
    stroke_id: str
    points: tuple[float, ...]


class AttachmentData(TransientEvent):
    """The picture of a board image, sent only to the person who asked for it."""

    type: Literal["attachment.data"] = "attachment.data"
    attachment_id: str
    media_type: str
    content_b64: str


class BoardErased(EventBase):
    type: Literal["board.erased"] = "board.erased"
    stroke_id: str


class BoardCleared(EventBase):
    """The board lost every mark, or only the marks of author_id when it is set."""

    type: Literal["board.cleared"] = "board.cleared"
    by: str
    author_id: str | None = None


class ChatPosted(EventBase):
    type: Literal["chat.posted"] = "chat.posted"
    message_id: str
    author_id: str
    text: str
    to: str | None = None
    mentions: tuple[str, ...] = ()


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
    # A plugin's prompt: the command that sent it, and the short text the room sees in place of
    # the full one the agent gets.
    via: str | None = None
    display: str | None = None


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


class ContextCompacting(TransientEvent):
    type: Literal["context.compacting"] = "context.compacting"
    run_id: str
    tokens_before: int


class AgentsChanged(EventBase):
    type: Literal["agents.changed"] = "agents.changed"
    agents: tuple[AgentView, ...]


class UsageRecorded(EventBase):
    type: Literal["usage.recorded"] = "usage.recorded"
    lines: tuple[UsageLine, ...]


class McpChanged(EventBase):
    type: Literal["mcp.changed"] = "mcp.changed"
    servers: tuple[McpServerView, ...]


class ToolsLoaded(EventBase):
    type: Literal["tools.loaded"] = "tools.loaded"
    tools: tuple[str, ...]


class PluginsChanged(EventBase):
    type: Literal["plugins.changed"] = "plugins.changed"
    plugins: tuple[PluginView, ...]
    commands: tuple[PluginCommandView, ...]


class CommandInvoked(EventBase):
    type: Literal["command.invoked"] = "command.invoked"
    command: str
    args: str
    invoker_id: str


class CommandReplied(EventBase):
    type: Literal["command.replied"] = "command.replied"
    command: str
    invoker_id: str
    text: str
    ok: bool = True


class ContextUsage(EventBase):
    type: Literal["context.usage"] = "context.usage"
    context: ContextView


class ContextCompacted(EventBase):
    type: Literal["context.compacted"] = "context.compacted"
    run_id: str
    summary: str
    tokens_before: int


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


class PolicyRuleAdded(EventBase):
    type: Literal["policy.rule_added"] = "policy.rule_added"
    rule: PolicyRuleView


class PolicyRuleRemoved(EventBase):
    type: Literal["policy.rule_removed"] = "policy.rule_removed"
    rule_id: str


class AttachmentAdded(EventBase):
    type: Literal["attachment.added"] = "attachment.added"
    attachment: AttachmentMeta


class SessionWelcome(TransientEvent):
    type: Literal["session.welcome"] = "session.welcome"
    room: str
    token: str
    participant: Participant
    base_policy: tuple[PolicyRuleView, ...] = ()
    agent: str = ""


class SessionSnapshot(TransientEvent):
    type: Literal["session.snapshot"] = "session.snapshot"
    state: SessionState
    streaming: dict[str, str] = Field(default_factory=dict[str, str])
    typing: tuple[str, ...] = ()


class InviteCreated(TransientEvent):
    type: Literal["invite.created"] = "invite.created"
    code: str
    role: Role
    expires_at: datetime | None = None
    link: str
    reusable: bool = False


class ErrorRaised(TransientEvent):
    type: Literal["error"] = "error"
    code: ErrorCode
    message: str


Event = Annotated[
    ParticipantJoined
    | ParticipantLeft
    | ParticipantRoleChanged
    | ParticipantRevoked
    | PromptModeChanged
    | PermissionModeChanged
    | SkillsChanged
    | SkillsFound
    | AgentChanged
    | AdmissionChanged
    | JoinRequested
    | JoinResolved
    | AccessRequested
    | AccessResolved
    | BriefingRequested
    | BriefingResolved
    | BriefingDelivered
    | BriefingSharingChanged
    | BriefingImported
    | JoinPending
    | JoinRefused
    | PromptDequeued
    | ParticipantTyping
    | ParticipantSelected
    | ParticipantCursor
    | BoardOpened
    | BoardStroked
    | BoardMoved
    | AttachmentData
    | PluginShown
    | PluginAsked
    | PluginNotified
    | BoardErased
    | BoardCleared
    | ChatPosted
    | ProposalCreated
    | ProposalApproved
    | ProposalRejected
    | PromptAccepted
    | RunStarted
    | RunEnded
    | MessageStarted
    | MessageDelta
    | MessageEnded
    | ContextCompacting
    | ContextCompacted
    | ContextUsage
    | McpChanged
    | UsageRecorded
    | AgentsChanged
    | ToolsLoaded
    | PluginsChanged
    | CommandInvoked
    | CommandReplied
    | PluginLineSet
    | PluginContextAdded
    | ToolStarted
    | ToolOutput
    | ToolEnded
    | ApprovalRequested
    | ApprovalResolved
    | PolicyRuleAdded
    | PolicyRuleRemoved
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
