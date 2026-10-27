from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class Model(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="ignore", json_schema_serialization_defaults_required=True
    )


class Role(StrEnum):
    HOST = "host"
    PARTICIPANT = "participant"
    VIEWER = "viewer"


class ActorKind(StrEnum):
    HUMAN = "human"
    AGENT = "agent"
    SYSTEM = "system"


class Origin(StrEnum):
    DIRECT = "direct"
    PROPOSAL = "proposal"


class PromptMode(StrEnum):
    OPEN = "open"
    REVIEW = "review"


class PermissionMode(StrEnum):
    DEFAULT = "default"
    ACCEPT_EDITS = "accept_edits"
    PLAN = "plan"
    AUTO = "auto"


class SkillScope(StrEnum):
    PROJECT = "project"
    GLOBAL = "global"


class McpStatus(StrEnum):
    CONNECTING = "connecting"
    READY = "ready"
    FAILED = "failed"
    OFF = "off"


class DequeueReason(StrEnum):
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    DROPPED = "dropped"


class Delivery(StrEnum):
    NOW = "now"
    STEER = "steer"
    FOLLOW_UP = "follow_up"


class ProposalDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"


class ApprovalDecision(StrEnum):
    ONCE = "once"
    ALWAYS = "always"
    REJECT = "reject"
    BLOCK = "block"


class PolicyAction(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class ToolRisk(StrEnum):
    READ = "read"
    WRITE = "write"
    EXEC = "exec"


class RunEndReason(StrEnum):
    STOP = "stop"
    ABORTED = "aborted"
    ERROR = "error"
    LIMIT = "limit"


class EntryKind(StrEnum):
    PROMPT = "prompt"
    ASSISTANT = "assistant"
    TOOL = "tool"
    COMPACTION = "compaction"


class Actor(Model):
    id: str
    kind: ActorKind
    name: str


class Participant(Model):
    id: str
    name: str
    role: Role
    connected: bool = False


class Provenance(Model):
    initiator_id: str
    initiator_role: Role
    origin: Origin


class Usage(Model):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def prompt_tokens(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens

    def __add__(self, other: Self) -> Self:
        return self.model_copy(
            update={
                "input_tokens": self.input_tokens + other.input_tokens,
                "output_tokens": self.output_tokens + other.output_tokens,
                "cache_read_tokens": self.cache_read_tokens + other.cache_read_tokens,
                "cache_write_tokens": self.cache_write_tokens + other.cache_write_tokens,
            }
        )


class ToolCallView(Model):
    id: str
    name: str
    risk: ToolRisk
    subject: str = ""
    args: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])


class AttachmentMeta(Model):
    id: str
    name: str
    size: int
    sha256: str
    owner_id: str


class ProposalView(Model):
    id: str
    author_id: str
    text: str
    delivery: Delivery
    attachments: tuple[str, ...] = ()


class QueuedPrompt(Model):
    prompt_id: str
    author_id: str
    text: str
    delivery: Delivery


class ApprovalView(Model):
    id: str
    call: ToolCallView
    provenance: Provenance
    timeout_at: datetime
    suggested_patterns: tuple[str, ...] = ()


class PolicyRuleView(Model):
    id: str
    tool: str
    pattern: str
    action: PolicyAction


class SkillView(Model):
    name: str
    description: str
    scope: SkillScope


class SkillHit(Model):
    package: str
    name: str
    installs: int = 0


class McpServerView(Model):
    name: str
    transport: str
    scope: SkillScope
    status: McpStatus
    tools: int = 0
    error: str | None = None


class ContextView(Model):
    tokens: int
    window: int
    compact_at: float


class RunView(Model):
    id: str
    prompt_id: str
    provenance: Provenance


class TranscriptEntry(Model):
    id: str
    kind: EntryKind
    author_id: str | None = None
    text: str = ""
    tool: ToolCallView | None = None
    ok: bool | None = None
    output: str = ""


class SessionState(Model):
    last_seq: int = 0
    prompt_mode: PromptMode = PromptMode.OPEN
    permission_mode: PermissionMode = PermissionMode.DEFAULT
    participants: dict[str, Participant] = Field(default_factory=dict[str, Participant])
    proposals: dict[str, ProposalView] = Field(default_factory=dict[str, ProposalView])
    approvals: dict[str, ApprovalView] = Field(default_factory=dict[str, ApprovalView])
    attachments: dict[str, AttachmentMeta] = Field(default_factory=dict[str, AttachmentMeta])
    policy: tuple[PolicyRuleView, ...] = ()
    skills: tuple[SkillView, ...] = ()
    context: ContextView | None = None
    mcp: tuple[McpServerView, ...] = ()
    queue: tuple[QueuedPrompt, ...] = ()
    agent: str = ""
    summary: str | None = None
    run: RunView | None = None
    transcript: tuple[TranscriptEntry, ...] = ()
