from typing import Annotated, Literal

from pydantic import Field

from plural.protocol.models import (
    ApprovalDecision,
    Delivery,
    Model,
    PermissionMode,
    PolicyAction,
    PromptMode,
    ProposalDecision,
    Role,
    SkillScope,
)

MAX_PROMPT_CHARS = 32_000
MAX_CHAT_CHARS = 2_000
MAX_MENTIONS = 20


class ClientInfo(Model):
    kind: str
    version: str


class SessionHello(Model):
    type: Literal["session.hello"] = "session.hello"
    client: ClientInfo
    name: str | None = Field(default=None, min_length=1, max_length=40)
    invite: str | None = None
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


class TypingSet(Model):
    type: Literal["presence.typing"] = "presence.typing"
    typing: bool


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
    | TypingSet
    | QueueCancel
    | PolicyAdd
    | PolicyRemove
    | FileAttach,
    Field(discriminator="type"),
]
