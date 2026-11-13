import asyncio
from dataclasses import dataclass

from plural.agent.loop.events import AgentEvent
from plural.agent.providers.base import LLMProvider
from plural.host.transport.base import Connection
from plural.protocol.commands import BoardDraw, BoardErase, BoardMove, BoardOpen, BriefingImport
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
class ChatAccepted:
    """The host accepted what a chat service sent through the import link."""

    command: BriefingImport


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
    display: str | None = None
    # Sent by a run_end hook: the run it starts does not fire run_end hooks again.
    from_hook: bool = False


@dataclass(frozen=True, slots=True)
class PluginLineUpdate:
    plugin: str
    text: str


@dataclass(frozen=True, slots=True)
class PluginLineFlush:
    plugin: str


@dataclass(frozen=True, slots=True)
class PluginQuestion:
    """A plugin waits for `answer` from `invoker_id`; None means closed, timed out or gone."""

    command: str
    invoker_id: str
    kind: str
    title: str
    options: tuple[str, ...]
    default: str
    answer: "asyncio.Future[str | None]"


@dataclass(frozen=True, slots=True)
class PluginNotify:
    command: str
    invoker_id: str
    text: str


@dataclass(frozen=True, slots=True)
class PluginShow:
    command: str
    invoker_id: str
    title: str
    text: str


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
    | ChatAccepted
    | TeamSweep
    | SkillsReply
    | BoardRequest
    | PluginReply
    | PluginPrompt
    | PluginShow
    | PluginQuestion
    | PluginNotify
    | PluginLineUpdate
    | PluginLineFlush
)


@dataclass(frozen=True, slots=True)
class _Queued:
    message: InboxMessage
    external: bool = False


class Inbox:
    def __init__(self, *, external_limit: int = 1024) -> None:
        self._queue: asyncio.Queue[_Queued] = asyncio.Queue()
        self._external = asyncio.BoundedSemaphore(external_limit)

    def put(self, message: InboxMessage) -> None:
        self._queue.put_nowait(_Queued(message))

    async def put_external(self, message: Incoming | Disconnected) -> None:
        await self._external.acquire()
        self._queue.put_nowait(_Queued(message, external=True))

    async def get(self) -> InboxMessage:
        queued = await self._queue.get()
        if queued.external:
            self._external.release()
        return queued.message
