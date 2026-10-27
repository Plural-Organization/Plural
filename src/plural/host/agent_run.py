import asyncio
from collections.abc import Sequence

import structlog

from plural.agent.events import RunEnd
from plural.agent.loop import AgentLoop
from plural.agent.messages import Message, UserTurn
from plural.agent.providers.base import LLMProvider
from plural.host.inbox import AgentOutput, Inbox
from plural.protocol.models import RunEndReason

log = structlog.get_logger(__name__)

ABORT_GRACE_S = 5.0


class AgentRun:
    def __init__(self, loop: AgentLoop, inbox: Inbox) -> None:
        self._loop = loop
        self._inbox = inbox
        self._task: asyncio.Task[None] | None = None
        self._cancel = asyncio.Event()
        self._deadline: asyncio.TimerHandle | None = None

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

    def swap_provider(self, provider: LLMProvider, *, context_window: int | None) -> None:
        self._loop.swap_provider(provider, context_window=context_window)

    async def close(self) -> None:
        await self._loop.close()

    def request_compaction(self) -> None:
        self._loop.request_compaction()

    def restore(self, conversation: Sequence[Message]) -> None:
        self._loop.restore(conversation)

    def cancel_pending(self, prompt_id: str) -> bool:
        return self._loop.cancel_pending(prompt_id)

    def drain_pending(self) -> list[UserTurn]:
        return self._loop.drain_pending()

    def abort(self) -> None:
        self._cancel.set()
        task = self._task
        if task is not None and self._deadline is None:
            self._deadline = asyncio.get_running_loop().call_later(ABORT_GRACE_S, task.cancel)

    async def _drive(self, run_id: str, turn: UserTurn, cancel: asyncio.Event) -> None:
        try:
            async for event in self._loop.run(turn, cancel=cancel):
                self._inbox.put(AgentOutput(run_id, event))
        except asyncio.CancelledError:
            self._inbox.put(AgentOutput(run_id, RunEnd(RunEndReason.ABORTED, self._loop.usage)))
        except Exception as error:
            log.exception("agent.run_failed", run_id=run_id)
            self._inbox.put(
                AgentOutput(run_id, RunEnd(RunEndReason.ERROR, self._loop.usage, str(error)))
            )
        finally:
            if self._deadline is not None:
                self._deadline.cancel()
                self._deadline = None
