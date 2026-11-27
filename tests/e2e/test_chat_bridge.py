import asyncio
import os
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from plural.bridge.bridge import Bridge
from plural.bridge.model import Answer, Incoming, Notice, Person, Phase, Place, Pressed, Said
from plural.bridge.platform import Links
from plural.bridge.store import BridgeStore
from plural.client.reconnect import JoinLink, SessionClient
from plural.protocol.commands import ClientInfo, ParticipantRevoke
from plural.protocol.events import SessionSnapshot
from plural.protocol.running import RunningRoom
from tests.doubles import FakeProvider, reply, use_tool
from tests.e2e.support import Session, running_session

OWNER = Person("1", "Tamirlan")
GUEST = Person("2", "Askar")
GROUP = Place("fake", "-100", None, private=False)
HOME = Place("fake", "1", None, private=True)


@dataclass(slots=True)
class Shown:
    place: Place
    key: str
    view: Answer | Notice
    final: bool
    reply_to: str | None


class FakeChat:
    name = "fake"
    identity = "@fake_bot"
    links = Links()

    def __init__(self) -> None:
        self.inbox: asyncio.Queue[Incoming] = asyncio.Queue()
        self.shown: list[Shown] = []
        self.answers: list[tuple[str, str, bool]] = []
        self._changed = asyncio.Event()

    async def start(self) -> None:
        return None

    async def incoming(self) -> AsyncIterator[Incoming]:
        while True:
            yield await self.inbox.get()

    async def show(
        self,
        place: Place,
        key: str,
        view: Answer | Notice,
        *,
        final: bool = True,
        reply_to: str | None = None,
    ) -> None:
        copy = view if isinstance(view, Notice) else _copy(view)
        self.shown.append(Shown(place, key, copy, final, reply_to))
        self._changed.set()

    async def answer(self, pressed: Pressed, text: str = "", *, alert: bool = False) -> None:
        self.answers.append((pressed.data, text, alert))
        self._changed.set()

    async def close(self) -> None:
        return None

    async def until(self, found: Callable[[], Shown | None], timeout: float = 10) -> Shown:
        async with asyncio.timeout(timeout):
            while (hit := found()) is None:
                self._changed.clear()
                await self._changed.wait()
            return hit

    def last(self, key_prefix: str, *, final: bool | None = None) -> Shown | None:
        for shown in reversed(self.shown):
            if shown.key.startswith(key_prefix) and (final is None or shown.final is final):
                return shown
        return None


def _copy(answer: Answer) -> Answer:
    return Answer(
        asked_by=answer.asked_by,
        question=answer.question,
        steps=[
            type(step)(step.call_id, step.tool, step.subject, step.state) for step in answer.steps
        ],
        text=answer.text,
        phase=answer.phase,
        error=answer.error,
    )


@asynccontextmanager
async def bridged(
    session: Session, tmp_path: Path, *, link: bool = True, **options: float
) -> AsyncGenerator[tuple[FakeChat, BridgeStore]]:
    chat = FakeChat()
    store = BridgeStore(tmp_path / "bridge-data", "fake")
    store.pair(OWNER, store.pairing_code())
    if link:
        store.link(GROUP, session.host.room)
    store.remember_home(OWNER, HOME)
    entry = RunningRoom(
        room=session.host.room,
        host_link=session.host.host_link,
        workspace=str(tmp_path / "ws"),
        pid=os.getpid(),
        started_at=datetime.now(UTC),
    )
    bridge = Bridge(
        chat,
        store,
        rooms=lambda: [entry],
        client=ClientInfo(kind="test", version="0"),
        sync_s=0.05,
        **options,
    )
    running = asyncio.create_task(bridge.run())
    try:
        async with asyncio.timeout(10):
            while not (feed := bridge._feeds.get(session.host.room)) or not feed.online.is_set():  # pyright: ignore[reportPrivateUsage]
                await asyncio.sleep(0.02)
        yield chat, store
    finally:
        running.cancel()
        with suppress(asyncio.CancelledError):
            await running


def said(person: Person, text: str, ref: str) -> Said:
    return Said(GROUP, person, text, addressed=True, ref=ref)


async def test_an_owner_asks_in_the_group_and_the_answer_comes_back_as_a_reply(
    tmp_path: Path,
) -> None:
    provider = FakeProvider([reply("notes.txt has two lines")])
    async with (
        running_session(tmp_path, relayed=False, provider=provider) as session,
        bridged(session, tmp_path) as (chat, _),
    ):
        await chat.inbox.put(said(OWNER, "what is in notes.txt?", "41"))

        done = await chat.until(lambda: chat.last("run:", final=True))

    assert isinstance(done.view, Answer)
    assert done.view.phase is Phase.DONE
    assert done.view.text == "notes.txt has two lines"
    assert done.view.question == "what is in notes.txt?"
    assert done.place == GROUP
    assert done.reply_to == "41"


async def test_a_guest_writes_as_themselves_and_the_owner_approves_from_the_chat(
    tmp_path: Path,
) -> None:
    provider = FakeProvider([use_tool("bash", "b1", command="echo hi"), reply("it printed hi")])
    async with (
        running_session(tmp_path, relayed=False, provider=provider) as session,
        bridged(session, tmp_path) as (chat, _),
    ):
        await chat.inbox.put(said(GUEST, "run echo hi", "7"))

        asked = await chat.until(lambda: chat.last("approval:"))
        assert isinstance(asked.view, Notice)
        assert "run a command" in asked.view.text
        assert "echo hi" in asked.view.text
        allow = asked.view.choices[0][0]

        await chat.inbox.put(Pressed(GROUP, GUEST, allow.data, query="q1"))
        async with asyncio.timeout(5):
            while not chat.answers:
                await asyncio.sleep(0.02)
        assert chat.answers[-1] == (allow.data, "Only the owner of this bot can do that.", True)

        await chat.inbox.put(Pressed(GROUP, OWNER, allow.data, query="q2"))
        done = await chat.until(lambda: chat.last("run:", final=True))
        resolved = chat.last("approval:")

    participants = session.host.actor.state.participants.values()
    assert any(participant.name == "Askar" for participant in participants)
    assert isinstance(done.view, Answer)
    assert done.view.text == "it printed hi"
    assert done.view.asked_by == "Askar"
    assert [step.tool for step in done.view.steps] == ["bash"]
    assert resolved is not None
    assert isinstance(resolved.view, Notice)
    assert "Allowed once" in resolved.view.text
    assert not resolved.view.choices


async def test_a_chat_that_follows_no_session_is_told_how_to_link_one(tmp_path: Path) -> None:
    provider = FakeProvider([])
    async with (
        running_session(tmp_path, relayed=False, provider=provider) as session,
        bridged(session, tmp_path) as (chat, store),
    ):
        store.unlink(GROUP)
        await chat.inbox.put(said(OWNER, "hello", "3"))

        told = await chat.until(lambda: chat.last("say:"))

    assert isinstance(told.view, Notice)
    assert "/link" in told.view.text


async def test_talk_not_meant_for_the_bot_reaches_the_agent_with_the_next_question(
    tmp_path: Path,
) -> None:
    provider = FakeProvider([reply("deploy is on Friday")])
    async with (
        running_session(tmp_path, relayed=False, provider=provider) as session,
        bridged(session, tmp_path) as (chat, _),
    ):
        await chat.inbox.put(Said(GROUP, GUEST, "we moved the deploy to Friday", addressed=False))
        async with asyncio.timeout(10):
            while not session.host.actor.state.chat:
                await asyncio.sleep(0.02)
        await chat.inbox.put(said(OWNER, "when is the deploy?", "9"))
        done = await chat.until(lambda: chat.last("run:", final=True))

    assert isinstance(done.view, Answer)
    assert done.view.text == "deploy is on Friday"
    seen = provider.requests[-1].model_dump_json()
    assert "we moved the deploy to Friday" in seen
    assert "Askar" in seen
    assert not [shown for shown in chat.shown if shown.key.startswith("say:")]


async def test_a_long_run_alerts_the_owner_in_the_private_chat_that_does_not_follow(
    tmp_path: Path,
) -> None:
    provider = FakeProvider([reply("the build is green")])
    async with (
        running_session(tmp_path, relayed=False, provider=provider) as session,
        bridged(session, tmp_path, alert_after_s=0) as (chat, _),
    ):
        await chat.inbox.put(said(OWNER, "run the build", "5"))

        alert = await chat.until(lambda: chat.last("alert:"))

    assert alert.place == HOME
    assert isinstance(alert.view, Notice)
    assert "ws" in alert.view.text
    assert "finished" in alert.view.text
    assert "the build is green" in alert.view.text
    assert alert.view.choices[0][0].data == f"link:{session.host.room}"


async def test_a_short_run_does_not_alert(tmp_path: Path) -> None:
    provider = FakeProvider([reply("quick")])
    async with (
        running_session(tmp_path, relayed=False, provider=provider) as session,
        bridged(session, tmp_path) as (chat, _),
    ):
        await chat.inbox.put(said(OWNER, "hi", "5"))
        await chat.until(lambda: chat.last("run:", final=True))
        await asyncio.sleep(0.2)

    assert chat.last("alert:") is None


async def test_a_muted_owner_gets_no_alert(tmp_path: Path) -> None:
    provider = FakeProvider([reply("done")])
    async with (
        running_session(tmp_path, relayed=False, provider=provider) as session,
        bridged(session, tmp_path, alert_after_s=0) as (chat, store),
    ):
        store.mute(OWNER, True)
        await chat.inbox.put(said(OWNER, "go", "5"))
        await chat.until(lambda: chat.last("run:", final=True))
        await asyncio.sleep(0.2)

    assert chat.last("alert:") is None


async def test_an_approval_nobody_answers_reaches_the_owner_and_can_be_answered_there(
    tmp_path: Path,
) -> None:
    provider = FakeProvider([use_tool("bash", "b1", command="echo hi"), reply("it printed hi")])
    async with (
        running_session(tmp_path, relayed=False, provider=provider) as session,
        bridged(session, tmp_path, approval_delay_s=0.05) as (chat, _),
    ):
        await chat.inbox.put(said(GUEST, "run echo hi", "7"))

        asked = await chat.until(
            lambda: next(
                (
                    shown
                    for shown in chat.shown
                    if shown.place == HOME and shown.key.startswith("approval:")
                ),
                None,
            )
        )
        assert isinstance(asked.view, Notice)
        assert "in `ws`" in asked.view.text
        allow = asked.view.choices[0][0]

        await chat.inbox.put(Pressed(HOME, OWNER, allow.data, query="q"))
        await chat.until(lambda: chat.last("run:", final=True))
        settled = next(
            shown
            for shown in reversed(chat.shown)
            if shown.place == HOME and shown.key.startswith("approval:")
        )

    assert isinstance(settled.view, Notice)
    assert "Allowed once" in settled.view.text
    assert not settled.view.choices


async def test_an_approval_answered_at_the_terminal_never_reaches_the_phone(
    tmp_path: Path,
) -> None:
    provider = FakeProvider([use_tool("bash", "b1", command="echo hi"), reply("it printed hi")])
    async with (
        running_session(tmp_path, relayed=False, provider=provider) as session,
        bridged(session, tmp_path, approval_delay_s=30) as (chat, _),
    ):
        await chat.inbox.put(said(GUEST, "run echo hi", "7"))
        asked = await chat.until(lambda: chat.last("approval:"))
        assert isinstance(asked.view, Notice)
        await chat.inbox.put(Pressed(GROUP, OWNER, asked.view.choices[0][0].data, query="q"))
        await chat.until(lambda: chat.last("run:", final=True))

    assert [shown for shown in chat.shown if shown.place == HOME] == []


async def test_an_owner_who_writes_in_private_follows_the_one_running_session_by_itself(
    tmp_path: Path,
) -> None:
    provider = FakeProvider([reply("notes.txt has two lines")])
    async with (
        running_session(tmp_path, relayed=False, provider=provider) as session,
        bridged(session, tmp_path, link=False) as (chat, store),
    ):
        await chat.inbox.put(Said(HOME, OWNER, "what is in notes.txt?", addressed=True, ref="9"))

        done = await chat.until(lambda: chat.last("run:", final=True))

    assert done.place == HOME
    assert isinstance(done.view, Answer)
    assert done.view.text == "notes.txt has two lines"
    assert store.room_of(HOME) == session.host.room
    told = chat.last("linked:")
    assert told is not None
    assert isinstance(told.view, Notice)
    assert "Following `ws`" in told.view.text


async def revoke(session: Session, name: str) -> None:
    """The host removes a participant, the way the terminal does."""
    found = next(p for p in session.host.actor.state.participants.values() if p.name == name)
    host = SessionClient(
        JoinLink.parse(session.host.host_link),
        name="terminal",
        client=ClientInfo(kind="test", version="0"),
    )
    joined = asyncio.Event()

    async def read() -> None:
        async for event in host.events():
            if isinstance(event, SessionSnapshot):
                joined.set()

    reading = asyncio.create_task(read())
    try:
        async with asyncio.timeout(5):
            await joined.wait()
        await host.send(ParticipantRevoke(participant_id=found.id))
    finally:
        reading.cancel()
        with suppress(asyncio.CancelledError):
            await reading


@pytest.mark.parametrize("bridge_is_down", [False, True])
async def test_a_guest_the_host_removed_is_not_brought_back(
    tmp_path: Path, bridge_is_down: bool
) -> None:
    provider = FakeProvider([reply("one"), reply("two")])
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        async with bridged(session, tmp_path) as (chat, store):
            await chat.inbox.put(said(GUEST, "first", "1"))
            await chat.until(lambda: chat.last("run:", final=True))
            if not bridge_is_down:
                await revoke(session, GUEST.name)
        if bridge_is_down:
            await revoke(session, GUEST.name)

        async with bridged(session, tmp_path) as (chat, store):
            await chat.inbox.put(said(GUEST, "second", "2"))
            told = await chat.until(lambda: chat.last("say:"))

        names = [p.name for p in session.host.actor.state.participants.values()]
        assert isinstance(told.view, Notice)
        assert "removed you" in told.view.text
        assert GUEST.name not in names
        assert store.is_revoked(session.host.room, GUEST.id)
