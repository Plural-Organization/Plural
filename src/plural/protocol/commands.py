from typing import Annotated, Literal

from pydantic import Field

from plural.protocol.models import (
    BOARD_POINTS_LIMIT,
    BOARD_TEXT_CHARS,
    AdmissionMode,
    ApprovalDecision,
    BoardCursor,
    BoardShape,
    BriefingSharing,
    Color,
    Delivery,
    Model,
    PermissionMode,
    PolicyAction,
    PromptMode,
    ProposalDecision,
    Role,
    SkillScope,
    TextSelection,
    Unit,
)

MAX_PROMPT_CHARS = 32_000
MAX_CHAT_CHARS = 2_000
MAX_BRIEFING_CHARS = 20_000
MAX_MENTIONS = 20


class ClientInfo(Model):
    kind: str
    version: str


class TeamProof(Model):
    certificate: str = Field(min_length=1, max_length=2048)
    url: str = Field(min_length=8, max_length=300)
    ts: int = Field(ge=0)
    nonce: str = Field(min_length=8, max_length=64)
    proof: str = Field(min_length=1, max_length=200)


class SessionHello(Model):
    type: Literal["session.hello"] = "session.hello"
    client: ClientInfo
    name: str | None = Field(default=None, min_length=1, max_length=40)
    invite: str | None = None
    join: str | None = None
    team: TeamProof | None = None
    token: str | None = None
    since: int | None = Field(default=None, ge=0)


class HistoryGet(Model):
    type: Literal["history.get"] = "history.get"
    before_seq: int | None = Field(default=None, ge=1)
    limit: int = Field(default=100, ge=1, le=500)


class PromptSubmit(Model):
    type: Literal["prompt.submit"] = "prompt.submit"
    text: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    attachments: tuple[str, ...] = ()
    delivery: Delivery = Delivery.NOW


class ChatSend(Model):
    type: Literal["chat.send"] = "chat.send"
    text: str = Field(min_length=1, max_length=MAX_CHAT_CHARS)
    to: str | None = None
    mentions: tuple[str, ...] = ()


class ProposalDecide(Model):
    type: Literal["proposal.decide"] = "proposal.decide"
    proposal_id: str
    decision: ProposalDecision
    edited_text: str | None = Field(default=None, min_length=1, max_length=MAX_PROMPT_CHARS)


class ApprovalRespond(Model):
    type: Literal["approval.respond"] = "approval.respond"
    approval_id: str
    decision: ApprovalDecision


class RunAbort(Model):
    type: Literal["run.abort"] = "run.abort"


class InviteCreate(Model):
    type: Literal["invite.create"] = "invite.create"
    role: Role = Role.PARTICIPANT
    ttl_s: int = Field(default=3600, ge=60, le=86_400)
    reusable: bool = False


class JoinDecide(Model):
    type: Literal["join.decide"] = "join.decide"
    request_id: str
    decision: Literal["allow", "viewer", "deny"]


class LinkRevoke(Model):
    type: Literal["link.revoke"] = "link.revoke"


class AdmissionSet(Model):
    type: Literal["link.set_admission"] = "link.set_admission"
    mode: AdmissionMode


class AccessRequest(Model):
    type: Literal["access.request"] = "access.request"
    note: str | None = Field(default=None, min_length=1, max_length=200)


class BriefingRequest(Model):
    type: Literal["briefing.request"] = "briefing.request"
    focus: str | None = Field(default=None, min_length=1, max_length=300)
    update: bool = False


class BriefingDecide(Model):
    type: Literal["briefing.decide"] = "briefing.decide"
    request_id: str
    decision: Literal["allow", "deny"]


class BriefingSharingSet(Model):
    type: Literal["session.set_briefing_sharing"] = "session.set_briefing_sharing"
    mode: BriefingSharing


class BriefingImport(Model):
    type: Literal["briefing.import"] = "briefing.import"
    source: str = Field(pattern=r"^\w[\w .@#-]{0,79}$")
    as_of_seq: int | None = Field(default=None, ge=0)
    text: str = Field(min_length=1, max_length=MAX_BRIEFING_CHARS)


class AccessDecide(Model):
    type: Literal["access.decide"] = "access.decide"
    participant_id: str
    decision: Literal["allow", "deny"]


class ParticipantSetRole(Model):
    type: Literal["participant.set_role"] = "participant.set_role"
    participant_id: str
    role: Role


class ParticipantRevoke(Model):
    type: Literal["participant.revoke"] = "participant.revoke"
    participant_id: str


class ContextCompact(Model):
    type: Literal["context.compact"] = "context.compact"


class PromptModeSet(Model):
    type: Literal["session.set_prompt_mode"] = "session.set_prompt_mode"
    mode: PromptMode


class PermissionModeSet(Model):
    type: Literal["session.set_permission_mode"] = "session.set_permission_mode"
    mode: PermissionMode


class SkillsSearch(Model):
    type: Literal["skills.search"] = "skills.search"
    query: str = Field(min_length=1, max_length=100)


class SkillsInstall(Model):
    type: Literal["skills.install"] = "skills.install"
    package: str = Field(min_length=3, max_length=200)
    scope: SkillScope = SkillScope.PROJECT


class SkillsRemove(Model):
    type: Literal["skills.remove"] = "skills.remove"
    name: str = Field(min_length=1, max_length=64)


class McpAdd(Model):
    type: Literal["mcp.add"] = "mcp.add"
    name: str = Field(min_length=1, max_length=32)
    command: str | None = Field(default=None, max_length=500)
    args: tuple[str, ...] = ()
    url: str | None = Field(default=None, max_length=500)
    env: dict[str, str] = Field(default_factory=dict[str, str])
    headers: dict[str, str] = Field(default_factory=dict[str, str])
    scope: SkillScope = SkillScope.PROJECT


class McpRemove(Model):
    type: Literal["mcp.remove"] = "mcp.remove"
    name: str = Field(min_length=1, max_length=32)


class McpToggle(Model):
    type: Literal["mcp.toggle"] = "mcp.toggle"
    name: str = Field(min_length=1, max_length=32)
    enabled: bool


class McpRestart(Model):
    type: Literal["mcp.restart"] = "mcp.restart"
    name: str = Field(min_length=1, max_length=32)


class McpImport(Model):
    type: Literal["mcp.import"] = "mcp.import"


class AgentsCreate(Model):
    type: Literal["agents.create"] = "agents.create"
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=300)
    prompt: str = Field(min_length=1, max_length=8000)
    tools: tuple[str, ...] = ()
    model: Literal["fast", "main"] = "fast"
    scope: SkillScope = SkillScope.PROJECT


class AgentsRemove(Model):
    type: Literal["agents.remove"] = "agents.remove"
    name: str = Field(min_length=1, max_length=64)


class TypingSet(Model):
    type: Literal["presence.typing"] = "presence.typing"
    typing: bool


class SelectionSet(Model):
    type: Literal["presence.select"] = "presence.select"
    selection: TextSelection | None


class CursorSet(Model):
    type: Literal["presence.cursor"] = "presence.cursor"
    cursor: BoardCursor | None


class BoardOpen(Model):
    type: Literal["board.open"] = "board.open"
    open: bool


class BoardDraw(Model):
    type: Literal["board.draw"] = "board.draw"
    kind: BoardShape = BoardShape.PEN
    text: str | None = Field(default=None, min_length=1, max_length=BOARD_TEXT_CHARS)
    image: str | None = Field(default=None, max_length=64)
    color: Color
    width: float = Field(ge=0.5, le=40)
    points: tuple[Unit, ...] = Field(min_length=2, max_length=BOARD_POINTS_LIMIT)


class BoardMove(Model):
    """Moves or resizes a mark: its points, the same kind and count as before."""

    type: Literal["board.move"] = "board.move"
    stroke_id: str
    points: tuple[Unit, ...] = Field(min_length=2, max_length=BOARD_POINTS_LIMIT)


class AttachmentFetch(Model):
    """Asks for the picture of an image on the board; only those are handed out."""

    type: Literal["attachment.fetch"] = "attachment.fetch"
    attachment_id: str = Field(max_length=64)


class BoardErase(Model):
    type: Literal["board.erase"] = "board.erase"
    stroke_id: str


class BoardClear(Model):
    """Clears the board; with mine, only the sender's own marks, which anyone who draws may do."""

    type: Literal["board.clear"] = "board.clear"
    mine: bool = False


class QueueCancel(Model):
    type: Literal["queue.cancel"] = "queue.cancel"
    prompt_id: str


class PolicyAdd(Model):
    type: Literal["policy.add"] = "policy.add"
    tool: str = Field(min_length=1, max_length=40)
    pattern: str = Field(min_length=1, max_length=200)
    action: PolicyAction


class PolicyRemove(Model):
    type: Literal["policy.remove"] = "policy.remove"
    rule_id: str


class FileAttach(Model):
    type: Literal["file.attach"] = "file.attach"
    name: str = Field(min_length=1, max_length=255)
    content_b64: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


Command = Annotated[
    SessionHello
    | HistoryGet
    | PromptSubmit
    | ChatSend
    | ProposalDecide
    | ApprovalRespond
    | RunAbort
    | InviteCreate
    | JoinDecide
    | AccessRequest
    | AccessDecide
    | BriefingRequest
    | BriefingDecide
    | BriefingSharingSet
    | BriefingImport
    | LinkRevoke
    | AdmissionSet
    | ParticipantSetRole
    | ParticipantRevoke
    | ContextCompact
    | PromptModeSet
    | PermissionModeSet
    | SkillsSearch
    | SkillsInstall
    | SkillsRemove
    | McpAdd
    | McpRemove
    | McpToggle
    | McpRestart
    | McpImport
    | AgentsCreate
    | AgentsRemove
    | TypingSet
    | SelectionSet
    | CursorSet
    | BoardOpen
    | BoardDraw
    | BoardMove
    | AttachmentFetch
    | BoardErase
    | BoardClear
    | QueueCancel
    | PolicyAdd
    | PolicyRemove
    | FileAttach,
    Field(discriminator="type"),
]
