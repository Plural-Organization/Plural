import asyncio
from dataclasses import dataclass

from plural.agent.events import AgentEvent
from plural.agent.providers.base import LLMProvider
from plural.host.transport.base import Connection
from plural.protocol.commands import BoardDraw, BoardErase, BoardMove, BoardOpen
from plural.protocol.envelope import Envelope
from plural.protocol.events import SkillsFound
from plural.protocol.models import ApprovalView, BriefingRequestView


@dataclass(frozen=True, slots=True)
class Incoming:
    connection: Connection
    envelope: Envelope


@dataclass(frozen=True, slots=True)
class Disconnected:
    connection: Connection


@dataclass(frozen=True, slots=True)
class AgentOutput:
    run_id: str
    event: AgentEvent


@dataclass(frozen=True, slots=True)
class ApprovalNeeded:
    approval: ApprovalView


@dataclass(frozen=True, slots=True)
class ApprovalExpired:
    approval_id: str


@dataclass(frozen=True, slots=True)
class JoinExpired:
    request_id: str


@dataclass(frozen=True, slots=True)
class TypingExpired:
    participant_id: str


@dataclass(frozen=True, slots=True)
class Reconfigure:
    provider: LLMProvider
    label: str
    context_window: int | None
    secrets: tuple[str, ...]
    reply: "asyncio.Future[None]"
    helper: LLMProvider | None = None
    helper_label: str = ""


@dataclass(frozen=True, slots=True)
class McpUpdated:
    pass


@dataclass(frozen=True, slots=True)
class SkillsUpdated:
    connection: Connection | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class TeamSweep:
    pass


@dataclass(frozen=True, slots=True)
class BriefingReady:
    request: BriefingRequestView
    text: str
    as_of_seq: int
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SkillsReply:
    connection: Connection
    event: SkillsFound | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class BoardRequest:
    """A board change by the agent, applied by the actor like a participant's."""

    command: BoardOpen | BoardDraw | BoardMove | BoardErase
    reply: "asyncio.Future[str]"


@dataclass(frozen=True, slots=True)
class PluginReply:
    command: str
    invoker_id: str
    text: str
    ok: bool = True


@dataclass(frozen=True, slots=True)
class PluginPrompt:
    command: str
    invoker_id: str
    text: str
    follow_up: bool = False


InboxMessage = (
    Incoming
    | Disconnected
    | AgentOutput
    | ApprovalNeeded
    | ApprovalExpired
    | TypingExpired
    | JoinExpired
    | Reconfigure
    | SkillsUpdated
    | McpUpdated
    | BriefingReady
    | TeamSweep
    | SkillsReply
    | BoardRequest
    | PluginReply
    | PluginPrompt
)


class Inbox:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[InboxMessage] = asyncio.Queue()

    def put(self, message: InboxMessage) -> None:
        self._queue.put_nowait(message)

    async def get(self) -> InboxMessage:
        return await self._queue.get()
