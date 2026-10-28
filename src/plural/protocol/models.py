from datetime import datetime
from enum import StrEnum
from typing import Annotated, Final, Self

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


HOST_PARTICIPANT_ID: Final = "p_host"


class AdmissionMode(StrEnum):
    APPROVE = "approve"
    OPEN = "open"


class JoinDecision(StrEnum):
    ALLOW = "allow"
    VIEWER = "viewer"
    DENY = "deny"
    EXPIRED = "expired"
    GONE = "gone"
    REVOKED = "revoked"


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


class TextSelection(Model):
    """Text someone has selected, as offsets into the text of one item on screen.

    The anchor names the item (a feed entry or a canvas document); every client lays
    out the same items, so the offsets point at the same words for everyone.
    """

    anchor: str = Field(min_length=1, max_length=200)
    start: int = Field(ge=0, le=1_000_000)
    end: int = Field(ge=0, le=1_000_000)


BOARD_STROKES_LIMIT: Final = 2000
BOARD_POINTS_LIMIT: Final = 4000
# All strokes together keep this many numbers at most, so a snapshot of the board stays near 1.5 MB,
# well under the 4 MiB a message may carry; the oldest strokes go first.
BOARD_TOTAL_POINTS: Final = 200_000
# Four decimals place a point within a tenth of a pixel on a 1000 px board.
BOARD_DECIMALS: Final = 4

# A point on the shared board, measured in board widths on both axes, so a taller screen shows more
# of the board below instead of stretching it; the board runs four widths down.
Unit = Annotated[float, Field(ge=0, le=4)]
Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]


class BoardShape(StrEnum):
    PEN = "pen"
    LINE = "line"
    ARROW = "arrow"
    RECT = "rect"
    ELLIPSE = "ellipse"
    TEXT = "text"


BOARD_TEXT_CHARS: Final = 500


class BoardStroke(Model):
    """One mark on the shared board; points are x0, y0, x1, y1, … in board units.

    A pen keeps every point, a shape its two corners, a text the point it starts at.
    """

    id: str
    author_id: str
    kind: BoardShape = BoardShape.PEN
    color: Color
    width: float = Field(ge=0.5, le=40)
    points: tuple[Unit, ...] = Field(min_length=2, max_length=BOARD_POINTS_LIMIT)
    text: str | None = Field(default=None, max_length=BOARD_TEXT_CHARS)


class BoardView(Model):
    open: bool = False
    strokes: tuple[BoardStroke, ...] = ()


class BoardCursor(Model):
    """Where someone points on the board; with ink, the pen is down and draws."""

    x: Unit
    y: Unit
    ink: bool = False
    color: Color | None = None
    width: float | None = Field(default=None, ge=0.5, le=40)


class ChatEntry(Model):
    id: str
    author_id: str
    text: str
    ts: datetime
    to: str | None = None
    mentions: tuple[str, ...] = ()


class JoinRequestView(Model):
    id: str
    name: str
    client: str
    requested_at: datetime


class SessionState(Model):
    last_seq: int = 0
    prompt_mode: PromptMode = PromptMode.OPEN
    permission_mode: PermissionMode = PermissionMode.DEFAULT
    admission: AdmissionMode = AdmissionMode.APPROVE
    join_requests: dict[str, JoinRequestView] = Field(default_factory=dict[str, JoinRequestView])
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
    chat: tuple[ChatEntry, ...] = ()
    board: BoardView = Field(default_factory=BoardView)
