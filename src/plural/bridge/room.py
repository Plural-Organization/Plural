"""One room seen from a chat: what happens in it goes to every chat that follows it, and what
people write there goes into it.

The feed joins the room with the host link of a host running on this computer
(`storage/running.py`), so it can answer approvals and stop runs. It never acts on its own: an
approval is answered only after an owner presses a button (`bridge.py` checks who pressed).
Someone in the chat who is not an owner writes through a connection of their own, joined with a
participant invite, so the room sees them by name and treats their prompts as a guest's.
"""

import asyncio
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field

import structlog

from plural.bridge.model import (
    Answer,
    Choice,
    Notice,
    Person,
    Phase,
    Place,
    Said,
    Step,
    StepState,
    Tone,
)
from plural.bridge.platform import ChatPlatform
from plural.client.connection import CommandRejected
from plural.client.reconnect import JoinLink, SessionClient
from plural.protocol.commands import (
    MAX_CHAT_CHARS,
    ApprovalRespond,
    ChatSend,
    ClientInfo,
    InviteCreate,
    PromptSubmit,
    RunAbort,
)
from plural.protocol.events import (
    ApprovalRequested,
    ApprovalResolved,
    Event,
    InviteCreated,
    MessageDelta,
    MessageEnded,
    MessageStarted,
    PromptAccepted,
    RunEnded,
    RunStarted,
    SessionSnapshot,
    SessionWelcome,
    ToolEnded,
    ToolStarted,
)
from plural.protocol.models import ApprovalDecision, ApprovalView, Role, RunEndReason
from plural.protocol.running import RunningRoom

log = structlog.get_logger(__name__)

POLL_S = 2.0
JOIN_TIMEOUT_S = 15.0
MAX_PROMPT = 20_000

DECIDED = {
    ApprovalDecision.ONCE: "✅ Allowed once",
    ApprovalDecision.ALWAYS: "✅ Always allowed",
    ApprovalDecision.REJECT: "⛔ Rejected",
    ApprovalDecision.BLOCK: "⛔ Blocked",
    ApprovalDecision.READ: "📖 Opened for reading",
    ApprovalDecision.WRITE: "✏️ Opened for writing",
}
RISKY = {"edit": "change a file", "write": "write a file", "bash": "run a command"}


class ApprovalBook:
    """Short names for approvals, since a button carries at most 64 bytes."""

    def __init__(self) -> None:
        self._next = 0
        self._by_short: dict[str, tuple[str, str]] = {}
        self._short: dict[tuple[str, str], str] = {}

    def short(self, room: str, approval_id: str) -> str:
        key = (room, approval_id)
        if key not in self._short:
            self._next += 1
            self._short[key] = str(self._next)
            self._by_short[self._short[key]] = key
        return self._short[key]

    def find(self, short: str) -> tuple[str, str] | None:
        return self._by_short.get(short)

    def forget(self, room: str, approval_id: str) -> None:
        short = self._short.pop((room, approval_id), None)
        if short is not None:
            self._by_short.pop(short, None)


@dataclass(slots=True)
class _Run:
    answer: Answer
    origin: tuple[Place, str | None] | None = None
    message: str | None = None
    texts: dict[str, str] = field(default_factory=dict[str, str])


@dataclass(slots=True)
class _Guest:
    client: SessionClient
    task: asyncio.Task[None]


@dataclass(frozen=True, slots=True)
class _Sent:
    author: str
    text: str
    place: Place
    ref: str | None


class RoomFeed:
    def __init__(
        self,
        room: str,
        platform: ChatPlatform,
        *,
        places: Callable[[], list[Place]],
        lookup: Callable[[str], RunningRoom | None],
        approvals: ApprovalBook,
        client: ClientInfo,
        poll_s: float = POLL_S,
    ) -> None:
        self.room = room
        self._platform = platform
        self._places = places
        self._lookup = lookup
        self._book = approvals
        self._client = client
        self._poll_s = poll_s
        self._host: SessionClient | None = None
        self._runs: dict[str, _Run] = {}
        self._messages: dict[str, str] = {}
        self._prompts: dict[str, tuple[str, str, _Sent | None]] = {}
        self._sent: list[_Sent] = []
        self._shown: dict[str, ApprovalView] = {}
        self._guests: dict[str, _Guest] = {}
        self._invite: asyncio.Future[str] | None = None
        self._invite_lock = asyncio.Lock()
        self.online = asyncio.Event()
        self.workspace: str | None = None

    async def run(self) -> None:
        """Follows the room for as long as the bridge runs, through host restarts."""
        while True:
            entry = self._lookup(self.room)
            if entry is None:
                await asyncio.sleep(self._poll_s)
                continue
            self.workspace = entry.workspace
            host = SessionClient(
                JoinLink.parse(entry.host_link), name="bridge", client=self._client
            )
            reading = asyncio.create_task(self._read(host), name=f"feed:{self.room}")
            try:
                while not reading.done():
                    await asyncio.wait({reading}, timeout=self._poll_s)
                    now = self._lookup(self.room)
                    if now is None or now.pid != entry.pid:
                        break
            finally:
                reading.cancel()
                with suppress(asyncio.CancelledError):
                    await reading
                await self._went_offline()
            if not reading.cancelled() and reading.exception() is not None:
                await asyncio.sleep(self._poll_s)

    async def prompt(self, said: Said, *, as_owner: bool) -> None:
        """Sends what someone wrote to the agent, as the host for an owner, else as themselves."""
        text = said.text.strip()[:MAX_PROMPT]
        if not text:
            return
        client = self._require_host() if as_owner else await self._guest(said.person)
        me = client.projection.me_id or ""
        self._sent.append(_Sent(me, text, said.place, said.ref))
        try:
            await client.send(PromptSubmit(text=text))
        except BaseException:
            self._sent = [sent for sent in self._sent if sent.text != text or sent.author != me]
            raise

    async def chat(self, said: Said, *, as_owner: bool) -> None:
        """Posts talk from the chat to the room's chat. The agent reads it before its next run
        (in the room's `mention` chat mode), as a note from the person who wrote it."""
        text = said.text.strip()[:MAX_CHAT_CHARS]
        if not text:
            return
        client = self._require_host() if as_owner else await self._guest(said.person)
        await client.send(ChatSend(text=text))

    async def decide(self, approval_id: str, decision: ApprovalDecision) -> None:
        await self._require_host().send(ApprovalRespond(approval_id=approval_id, decision=decision))

    async def abort(self) -> None:
        await self._require_host().send(RunAbort())

    async def close(self) -> None:
        await self._drop_guests()

    # The room's events

    async def _read(self, host: SessionClient) -> None:
        self._host = host
        try:
            async for event in host.events():
                try:
                    await self._on(event)
                except Exception:
                    log.exception("bridge.event_failed", room=self.room, event=event.type)
        except CommandRejected as error:
            log.warning("bridge.host_refused", room=self.room, error=str(error))
            raise
        finally:
            self._host = None

    async def _on(self, event: Event) -> None:
        match event:
            case SessionWelcome():
                self.online.set()
            case SessionSnapshot(state=state):
                for approval in state.approvals.values():
                    await self._ask(approval)
            case InviteCreated(link=link):
                if self._invite is not None and not self._invite.done():
                    self._invite.set_result(link)
            case PromptAccepted(prompt_id=prompt_id, author_id=author, text=text):
                self._prompts[prompt_id] = (author, text, self._claim(author, text))
            case RunStarted(run_id=run_id, prompt_id=prompt_id):
                await self._started(run_id, prompt_id)
            case MessageStarted(run_id=run_id, message_id=message_id):
                self._messages[message_id] = run_id
                if (run := self._runs.get(run_id)) is not None:
                    run.message = message_id
            case MessageDelta(message_id=message_id, text=text, thinking=False):
                await self._delta(message_id, text)
            case MessageEnded(run_id=run_id, message_id=message_id, text=text):
                self._messages.pop(message_id, None)
                if (run := self._runs.get(run_id)) is not None and text.strip():
                    run.answer.text = text
            case ToolStarted(run_id=run_id, call=call):
                if (run := self._runs.get(run_id)) is not None:
                    run.answer.steps.append(Step(call.id, call.name, call.subject))
                    run.answer.phase = Phase.WORKING
                    await self._show(run_id, final=False)
            case ToolEnded(run_id=run_id, call_id=call_id, ok=ok):
                if (run := self._runs.get(run_id)) is not None:
                    for step in run.answer.steps:
                        if step.call_id == call_id:
                            step.state = StepState.OK if ok else StepState.FAILED
                    await self._show(run_id, final=False)
            case ApprovalRequested(approval=approval):
                await self._ask(approval)
            case ApprovalResolved(approval_id=approval_id, decision=decision, resolved_by=by):
                await self._resolved(approval_id, decision, by)
            case RunEnded(run_id=run_id, reason=reason, error=error):
                await self._ended(run_id, reason, error)
            case _:
                pass

    def _claim(self, author: str, text: str) -> _Sent | None:
        for index, sent in enumerate(self._sent):
            if sent.author == author and sent.text == text:
                return self._sent.pop(index)
        return None

    def _name(self, participant_id: str) -> str:
        host = self._host
        participant = host.projection.state.participants.get(participant_id) if host else None
        return participant.name if participant is not None else "someone"

    async def _started(self, run_id: str, prompt_id: str) -> None:
        author, question, sent = self._prompts.pop(prompt_id, ("", "", None))
        answer = Answer(asked_by=self._name(author) if author else None, question=question)
        run = _Run(answer, origin=None if sent is None else (sent.place, sent.ref))
        self._runs[run_id] = run
        await self._show(run_id, final=False)

    async def _delta(self, message_id: str, text: str) -> None:
        run_id = self._messages.get(message_id)
        run = self._runs.get(run_id) if run_id else None
        if run is None or run_id is None:
            return
        run.texts[message_id] = run.texts.get(message_id, "") + text
        if run.texts[message_id].strip():
            run.answer.text = run.texts[message_id]
            run.answer.phase = Phase.WORKING
            await self._show(run_id, final=False)

    async def _ended(self, run_id: str, reason: RunEndReason, error: str | None) -> None:
        run = self._runs.pop(run_id, None)
        if run is None:
            return
        for message_id in [key for key, owner in self._messages.items() if owner == run_id]:
            self._messages.pop(message_id, None)
        run.answer.phase = {
            RunEndReason.STOP: Phase.DONE,
            RunEndReason.ABORTED: Phase.STOPPED,
        }.get(reason, Phase.FAILED)
        if run.answer.phase is Phase.FAILED:
            run.answer.error = error or (
                "the step limit was reached" if reason is RunEndReason.LIMIT else ""
            )
        for step in run.answer.steps:
            if step.state is StepState.RUNNING:
                step.state = StepState.FAILED
        await self._render(run_id, run, final=True)

    async def _show(self, run_id: str, *, final: bool) -> None:
        run = self._runs.get(run_id)
        if run is not None:
            await self._render(run_id, run, final=final)

    async def _render(self, run_id: str, run: _Run, *, final: bool) -> None:
        for place in self._places():
            here = run.origin is not None and run.origin[0] == place
            try:
                await self._platform.show(
                    place,
                    f"run:{self.room}:{run_id}",
                    run.answer,
                    final=final,
                    reply_to=run.origin[1] if here and run.origin else None,
                )
            except Exception:
                log.exception("bridge.show_failed", room=self.room, place=place.key)

    async def _ask(self, approval: ApprovalView) -> None:
        if approval.id in self._shown:
            return
        self._shown[approval.id] = approval
        notice = approval_notice(approval, self._book.short(self.room, approval.id))
        await self._notify(f"approval:{self.room}:{approval.id}", notice)

    async def _resolved(self, approval_id: str, decision: ApprovalDecision, by: str | None) -> None:
        approval = self._shown.pop(approval_id, None)
        self._book.forget(self.room, approval_id)
        if approval is None:
            return
        who = f" · {self._name(by)}" if by else ""
        notice = approval_notice(approval, None, outcome=f"**{DECIDED[decision]}**{who}")
        await self._notify(f"approval:{self.room}:{approval_id}", notice)

    async def _notify(self, key: str, notice: Notice) -> None:
        for place in self._places():
            try:
                await self._platform.show(place, key, notice)
            except Exception:
                log.exception("bridge.show_failed", room=self.room, place=place.key)

    async def _went_offline(self) -> None:
        self.online.clear()
        await self._drop_guests()
        for run_id, run in list(self._runs.items()):
            run.answer.phase = Phase.FAILED
            run.answer.error = "the session went offline"
            await self._render(run_id, run, final=True)
        self._runs.clear()
        self._messages.clear()
        for approval_id, approval in list(self._shown.items()):
            self._book.forget(self.room, approval_id)
            notice = approval_notice(approval, None, outcome="_The session went offline._")
            await self._notify(f"approval:{self.room}:{approval_id}", notice)
        self._shown.clear()

    # Connections

    def _require_host(self) -> SessionClient:
        if self._host is None or not self.online.is_set():
            raise ConnectionError("the session is not running")
        return self._host

    async def _guest(self, person: Person) -> SessionClient:
        guest = self._guests.get(person.id)
        if guest is not None and not guest.task.done():
            return guest.client
        link = await self._new_invite()
        client = SessionClient(JoinLink.parse(link), name=person.name[:40], client=self._client)
        welcomed = asyncio.Event()
        task = asyncio.create_task(self._drain(client, welcomed), name=f"guest:{person.id}")
        self._guests[person.id] = _Guest(client, task)
        try:
            async with asyncio.timeout(JOIN_TIMEOUT_S):
                await welcomed.wait()
        except TimeoutError:
            task.cancel()
            self._guests.pop(person.id, None)
            raise ConnectionError("could not join the session") from None
        return client

    async def _new_invite(self) -> str:
        host = self._require_host()
        async with self._invite_lock:
            self._invite = asyncio.get_running_loop().create_future()
            await host.send(InviteCreate(role=Role.PARTICIPANT, ttl_s=300))
            async with asyncio.timeout(JOIN_TIMEOUT_S):
                return await self._invite

    async def _drain(self, client: SessionClient, welcomed: asyncio.Event) -> None:
        with suppress(CommandRejected):
            async for event in client.events():
                if isinstance(event, SessionWelcome):
                    welcomed.set()

    async def _drop_guests(self) -> None:
        guests, self._guests = self._guests, {}
        for guest in guests.values():
            guest.task.cancel()
        for guest in guests.values():
            with suppress(asyncio.CancelledError, Exception):
                await guest.task


def approval_notice(approval: ApprovalView, short: str | None, *, outcome: str = "") -> Notice:
    """What the agent asks to do, and the buttons to answer it while it waits."""
    call = approval.call
    if approval.folder is not None:
        access = "read and write" if approval.folder.write else "read"
        lines = [
            f"**🔐 The agent asks to {access} a folder outside the project**",
            _block(approval.folder.folder),
        ]
    else:
        what = RISKY.get(call.name, f"use `{call.name}`")
        lines = [f"**🔐 The agent wants to {what}**"]
        if call.subject:
            lines.append(_block(call.subject))
    lines.extend(f"⚠️ {warning}" for warning in approval.warnings)
    if outcome:
        lines.append(outcome)
    choices: tuple[tuple[Choice, ...], ...] = ()
    if short is not None and not outcome:
        if approval.folder is not None:
            first = (
                Choice("📖 Read", f"ap:{short}:{ApprovalDecision.READ.value}", Tone.PRIMARY),
                Choice("✏️ Read and write", f"ap:{short}:{ApprovalDecision.WRITE.value}", Tone.GOOD),
            )
        else:
            first = (
                Choice("✅ Allow", f"ap:{short}:{ApprovalDecision.ONCE.value}", Tone.GOOD),
                Choice("Always", f"ap:{short}:{ApprovalDecision.ALWAYS.value}", Tone.PRIMARY),
            )
        choices = (
            first,
            (Choice("⛔ Reject", f"ap:{short}:{ApprovalDecision.REJECT.value}", Tone.DANGER),),
        )
    return Notice("\n\n".join(lines), choices)


def _block(text: str) -> str:
    fence = "````" if "```" in text else "```"
    return f"{fence}\n{text[:3000]}\n{fence}"
