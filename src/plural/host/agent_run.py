import asyncio

import structlog

from plural.agent.events import RunEnd
from plural.agent.loop import AgentLoop
from plural.agent.messages import UserTurn
from plural.host.inbox import AgentOutput, Inbox
from plural.protocol.models import RunEndReason, Usage

log = structlog.get_logger(__name__)


class AgentRun:
    def __init__(self, loop: AgentLoop, inbox: Inbox) -> None:
        self._loop = loop
        self._inbox = inbox
        self._task: asyncio.Task[None] | None = None
        self._cancel = asyncio.Event()

    @property
    def active(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, run_id: str, turn: UserTurn) -> None:
        if self.active:
            raise RuntimeError("a run is already active")
        self._cancel = asyncio.Event()
        self._task = asyncio.create_task(self._drive(run_id, turn, self._cancel), name=run_id)

    def steer(self, turn: UserTurn) -> None:
        self._loop.steer(turn)

    def follow_up(self, turn: UserTurn) -> None:
        self._loop.follow_up(turn)

    def drain_pending(self) -> list[UserTurn]:
        return self._loop.drain_pending()

    def abort(self) -> None:
        self._cancel.set()
        if self._task is not None:
            self._task.cancel()

    async def _drive(self, run_id: str, turn: UserTurn, cancel: asyncio.Event) -> None:
        try:
            async for event in self._loop.run(turn, cancel=cancel):
                self._inbox.put(AgentOutput(run_id, event))
        except asyncio.CancelledError:
            self._inbox.put(AgentOutput(run_id, RunEnd(RunEndReason.ABORTED, Usage())))
        except Exception as error:
            log.exception("agent.run_failed", run_id=run_id)
            self._inbox.put(AgentOutput(run_id, RunEnd(RunEndReason.ERROR, Usage(), str(error))))
