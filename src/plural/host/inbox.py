import asyncio
from dataclasses import dataclass

from plural.agent.events import AgentEvent
from plural.agent.providers.base import LLMProvider
from plural.host.transport.base import Connection
from plural.protocol.envelope import Envelope
from plural.protocol.events import SkillsFound
from plural.protocol.models import ApprovalView


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
class TypingExpired:
    participant_id: str


@dataclass(frozen=True, slots=True)
class Reconfigure:
    provider: LLMProvider
    label: str
    context_window: int | None
    secrets: tuple[str, ...]
    reply: "asyncio.Future[None]"


@dataclass(frozen=True, slots=True)
class McpUpdated:
    pass


@dataclass(frozen=True, slots=True)
class SkillsUpdated:
    connection: Connection | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SkillsReply:
    connection: Connection
    event: SkillsFound | None = None
    error: str | None = None


InboxMessage = (
    Incoming
    | Disconnected
    | AgentOutput
    | ApprovalNeeded
    | ApprovalExpired
    | TypingExpired
    | Reconfigure
    | SkillsUpdated
    | McpUpdated
    | SkillsReply
)


class Inbox:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[InboxMessage] = asyncio.Queue()

    def put(self, message: InboxMessage) -> None:
        self._queue.put_nowait(message)

    async def get(self) -> InboxMessage:
        return await self._queue.get()
