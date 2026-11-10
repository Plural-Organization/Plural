import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence

import structlog

from plural.agent.loop.events import AgentEvent, ContextFill, ContextNote, RunEnd, Spend
from plural.agent.loop.loop import AgentLoop
from plural.agent.loop.messages import PLUGIN_SOURCE, Message, NotesTurn, UserTurn
from plural.agent.providers.base import LLMProvider
from plural.host.inbox import AgentOutput, Inbox
from plural.protocol.models import RunEndReason

log = structlog.get_logger(__name__)

ABORT_GRACE_S = 5.0

# Plugin before_run hooks: the prompt in, (plugin, text) pairs out.
Prepare = Callable[[UserTurn], Awaitable[Sequence[tuple[str, str]]]]


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

    def start(self, run_id: str, turn: UserTurn, prepare: Prepare | None = None) -> None:
        self._launch(run_id, lambda cancel: self._run(turn, prepare, cancel))

    async def _run(
        self, turn: UserTurn, prepare: Prepare | None, cancel: asyncio.Event
    ) -> AsyncIterator[AgentEvent]:
        # Plugin hooks run in the run's task, so a slow one never holds up the room.
        for plugin, text in await prepare(turn) if prepare is not None else ():
            if self._loop.add_context(NotesTurn(source=f"{PLUGIN_SOURCE}{plugin}", text=text)):
                yield ContextNote(plugin, text)
        async for event in self._loop.run(turn, cancel=cancel):
            yield event

    def compact(self, run_id: str) -> None:
        self._launch(run_id, lambda cancel: self._loop.compact(cancel=cancel))

    @property
    def can_compact(self) -> bool:
        return self._loop.can_compact

    def fill(self) -> ContextFill:
        return self._loop.fill()

    def take_spending(self) -> tuple[Spend, ...]:
        return self._loop.take_spending()

    def _launch(
        self, run_id: str, events: Callable[[asyncio.Event], AsyncIterator[AgentEvent]]
    ) -> None:
        if self.active:
            raise RuntimeError("a run is already active")
        self._cancel = asyncio.Event()
        self._task = asyncio.create_task(self._drive(run_id, events(self._cancel)), name=run_id)

    def steer(self, turn: UserTurn) -> None:
        self._loop.steer(turn)

    def follow_up(self, turn: UserTurn) -> None:
        self._loop.follow_up(turn)

    def swap_provider(
        self, provider: LLMProvider, *, context_window: int | None, helper: LLMProvider | None
    ) -> None:
        self._loop.swap_provider(provider, context_window=context_window, helper=helper)

    async def close(self) -> None:
        await self._loop.close()

    def request_compaction(self) -> None:
        self._loop.request_compaction()

    def load_tools(self, names: Sequence[str]) -> None:
        self._loop.load_tools(names)

    def restore(self, conversation: Sequence[Message]) -> None:
        self._loop.restore(conversation)

    def mark_shared(self) -> None:
        self._loop.mark_shared()

    def add_notes(self, turn: NotesTurn) -> None:
        self._loop.add_notes(turn)

    async def brief(self, instruction: str, *, cancel: asyncio.Event) -> str:
        return await self._loop.brief(instruction, cancel=cancel)

    async def ask(self, question: str, *, history: bool, main: bool) -> str:
        return await self._loop.ask(question, history=history, main=main, cancel=asyncio.Event())

    def cancel_pending(self, prompt_id: str) -> bool:
        return self._loop.cancel_pending(prompt_id)

    def drain_pending(self) -> list[UserTurn]:
        return self._loop.drain_pending()

    def abort(self) -> None:
        self._cancel.set()
        task = self._task
        if task is not None and self._deadline is None:
            self._deadline = asyncio.get_running_loop().call_later(ABORT_GRACE_S, task.cancel)

    async def _drive(self, run_id: str, events: AsyncIterator[AgentEvent]) -> None:
        # The task has its own context, so every line the run logs carries its id.
        structlog.contextvars.bind_contextvars(run_id=run_id)
        try:
            async for event in events:
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
