"""The bot's side of a chat: who may do what, which chat follows which room, and the commands.

One bot serves any number of chats and rooms. A chat (or a topic in a chat with topics) follows
one room at a time; a room can be followed from many chats. Owners are the people who paired with
the bot from a private chat with the code its runner printed; only they link chats, answer
approvals and stop runs. Anyone else in a linked chat who mentions the bot writes to the room as
a guest, so the room's own rules for guests apply to them.
"""

import asyncio
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import cast

import structlog

from plural.bridge.model import Choice, Incoming, Notice, Place, Pressed, Said, Tone
from plural.bridge.platform import ChatPlatform
from plural.bridge.room import (
    ALERT_AFTER_S,
    APPROVAL_DELAY_S,
    POLL_S,
    ApprovalBook,
    GuestRevoked,
    RoomFeed,
)
from plural.bridge.store import BridgeStore
from plural.client.connection import CommandRejected
from plural.protocol.commands import ClientInfo
from plural.protocol.models import ApprovalDecision
from plural.protocol.running import RunningRoom

log = structlog.get_logger(__name__)

HELP = """**Plural in this chat**

Start a message with "plural", mention me or reply to me to talk to the agent of the linked session.

/link: pick a session running on the host's computer for this chat
/unlink: stop following it here
/status: which session this chat follows
/stop: stop the agent's current run
/ask <text>: send a prompt without a mention
/mute, /unmute: alerts to your private chat about sessions it does not follow

In a private chat with its owner the bot follows the session running on the computer by itself. \
Only the bot's owner links chats, answers the agent's requests and stops runs. Everyone else \
writes to the session as a guest."""


class Bridge:
    def __init__(
        self,
        platform: ChatPlatform,
        store: BridgeStore,
        *,
        rooms: Callable[[], list[RunningRoom]],
        client: ClientInfo,
        alert_after_s: float = ALERT_AFTER_S,
        approval_delay_s: float = APPROVAL_DELAY_S,
        sync_s: float = POLL_S,
    ) -> None:
        self._alert_after_s = alert_after_s
        self._approval_delay_s = approval_delay_s
        self._sync_s = sync_s
        self._syncing: asyncio.Task[None] | None = None
        self._platform = platform
        self._store = store
        self._rooms = rooms
        self._client = client
        self._book = ApprovalBook()
        self._feeds: dict[str, RoomFeed] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._said_count = 0
        self._handling: set[asyncio.Task[None]] = set()
        self._locks: dict[str, asyncio.Lock] = {}

    async def run(self) -> None:
        await self._platform.start()
        for room in self._store.rooms:
            self._feed(room)
        self._syncing = asyncio.create_task(self._sync(), name="bridge:sync")
        try:
            async for item in self._platform.incoming():
                self._dispatch(item)
        finally:
            await self.close()

    def _dispatch(self, item: Incoming) -> None:
        """Handles an update on its own task. Talk in one place stays in order, but a slow turn
        (a guest joining the room takes seconds) never holds up another chat or a button that
        answers an approval."""
        lock = (
            None
            if isinstance(item, Pressed)
            else self._locks.setdefault(item.place.key, asyncio.Lock())
        )
        task = asyncio.create_task(self._handle(item, lock))
        self._handling.add(task)
        task.add_done_callback(self._handling.discard)

    async def _handle(self, item: Incoming, lock: asyncio.Lock | None) -> None:
        try:
            if lock is not None:
                async with lock:
                    await self._said(cast(Said, item))
            else:
                await self._pressed(cast(Pressed, item))
        except Exception:
            log.exception("bridge.handle_failed")

    async def _sync(self) -> None:
        """Keeps a feed on every running session while an owner wants alerts, so a session
        started at the terminal can reach their phone, and lets go of the ones that ended."""
        while True:
            try:
                await self._watch_rooms()
            except Exception:
                log.exception("bridge.sync_failed")
            await asyncio.sleep(self._sync_s)

    async def _watch_rooms(self) -> None:
        running = {entry.room for entry in self._rooms()}
        alerting = bool(self._store.alert_places())
        if alerting:
            for room in running:
                self._feed(room)
        keep: set[str] = set(self._store.rooms)
        if alerting:
            keep |= running
        for room in [room for room in self._feeds if room not in keep]:
            task = self._tasks.pop(room, None)
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task
            await self._feeds.pop(room).close()

    async def close(self) -> None:
        if self._syncing is not None:
            self._syncing.cancel()
            with suppress(asyncio.CancelledError):
                await self._syncing
            self._syncing = None
        for handling in list(self._handling):
            handling.cancel()
        for task in self._tasks.values():
            task.cancel()
        for room, task in list(self._tasks.items()):
            with suppress(asyncio.CancelledError, Exception):
                await task
            await self._feeds[room].close()
        self._tasks.clear()
        self._feeds.clear()
        with suppress(Exception):
            await self._platform.close()

    def _feed(self, room: str) -> RoomFeed:
        feed = self._feeds.get(room)
        if feed is None:
            feed = self._feeds[room] = RoomFeed(
                room,
                self._platform,
                places=lambda: self._store.places_of(room),
                lookup=self._lookup,
                approvals=self._book,
                client=self._client,
                store=self._store,
                alerts=self._store.alert_places,
                alert_after_s=self._alert_after_s,
                approval_delay_s=self._approval_delay_s,
            )
            self._tasks[room] = asyncio.create_task(feed.run(), name=f"room:{room}")
        return feed

    def _lookup(self, room: str) -> RunningRoom | None:
        return next((entry for entry in self._rooms() if entry.room == room), None)

    # Messages

    async def _said(self, said: Said) -> None:
        if said.place.private and self._store.is_owner(said.person):
            self._store.remember_home(said.person, said.place)
        if not said.addressed:
            await self._overheard(said)
            return
        command, _, rest = said.text.strip().partition(" ")
        if command.startswith("/"):
            await self._command(said, command[1:].lower(), rest.strip())
            return
        await self._prompt(said, said.text)

    async def _command(self, said: Said, name: str, rest: str) -> None:
        owner = self._store.is_owner(said.person)
        match name:
            case "start" | "help":
                if name == "start" and rest and not owner:
                    await self._pair(said, rest)
                elif said.place.private and not owner:
                    await self._say(said, _STRANGER)
                else:
                    await self._say(said, HELP)
                    if name == "start" and said.place.private:
                        await self._resolve(said)
            case "pair":
                await self._pair(said, rest)
            case "ask":
                await self._prompt(said, rest)
            case "link" if owner:
                await self._offer_rooms(said.place)
            case "unlink" if owner:
                room = self._store.unlink(said.place)
                await self._say(
                    said,
                    "This chat no longer follows a session."
                    if room
                    else "This chat follows no session.",
                )
            case "stop" if owner:
                await self._stop(said.place)
            case "status":
                await self._say(said, self._status(said.place))
            case "mute" | "unmute" if owner:
                await self._mute(said, muted=name == "mute")
            case "link" | "unlink" | "stop" | "mute" | "unmute":
                await self._say(said, "Only the owner of this bot can do that.")
            case _:
                pass

    async def _prompt(self, said: Said, text: str) -> None:
        if not text.strip():
            await self._say(
                said, "Write something after the command, or mention me with a question."
            )
            return
        owner = self._store.is_owner(said.person)
        room = await self._resolve(said)
        if room is None:
            if said.place.private and owner:
                return
            await self._say(
                said,
                "This chat follows no session yet. "
                + (
                    "Send /link to pick one."
                    if owner
                    else "The bot's owner can link one with /link."
                ),
            )
            return
        feed = self._feed(room)
        try:
            await feed.prompt(
                Said(said.place, said.person, text, said.addressed, said.ref),
                as_owner=self._store.is_owner(said.person),
            )
        except (ConnectionError, TimeoutError):
            await self._say(
                said,
                "The session is not running. Start it on the host's computer, "
                "and this chat reconnects on its own.",
            )
        except CommandRejected as error:
            await self._say(said, f"The session refused it: {error.error.message}")
        except GuestRevoked:
            await self._say(said, "The host removed you from this session.")

    async def _resolve(self, said: Said) -> str | None:
        """The session this chat follows. In an owner's private chat nobody has to link one: when
        a single session runs on this computer, the chat follows it, and moves to the next one
        when the session it followed is gone. With several running, it asks which. A chat that
        is not an owner's private chat follows only what its owner linked."""
        place = said.place
        room = self._store.room_of(place)
        if not (place.private and self._store.is_owner(said.person)):
            return room
        if room is not None and self._lookup(room) is not None:
            return room
        if room is not None:
            self._store.unlink(place)
            room = None
        running = self._rooms()
        if len(running) == 1:
            entry = running[0]
            self._store.link(place, entry.room)
            self._feed(entry.room)
            await self._platform.show(
                place,
                self._key("linked"),
                Notice(
                    f"Following `{_project(entry)}`. Mention me to talk to its agent; "
                    "/link picks another session."
                ),
            )
            return entry.room
        if room is None and not running:
            await self._platform.show(
                place,
                self._key("link"),
                Notice(
                    "No session is running on this computer. Start `plural` in a project folder "
                    "and write to me again: I follow it by myself."
                ),
            )
        elif room is None:
            await self._offer_rooms(place, again=True)
        return room

    async def _mute(self, said: Said, *, muted: bool) -> None:
        if not self._store.mute(said.person, muted):
            await self._say(
                said, "Write to me in a private chat first, so I know where to reach you."
            )
        elif muted:
            await self._say(said, "Muted. /unmute brings the alerts back.")
        else:
            await self._say(
                said,
                "I will write here when a session needs your answer, "
                "and when a long run finishes in one this chat does not follow.",
            )

    async def _overheard(self, said: Said) -> None:
        """Talk in a linked chat that is not meant for the bot goes to the room's chat, so the
        agent knows what the group said when it is next asked. It never answers it."""
        room = self._store.room_of(said.place)
        if room is None or said.text.startswith("/"):
            return
        try:
            await self._feed(room).chat(said, as_owner=self._store.is_owner(said.person))
        except (ConnectionError, TimeoutError, CommandRejected, GuestRevoked) as error:
            log.info("bridge.chat_dropped", room=room, error=str(error))

    async def _pair(self, said: Said, code: str) -> None:
        if not said.place.private:
            await self._say(said, "Pair in a private chat with me, so nobody else sees the code.")
            return
        if self._store.is_owner(said.person):
            await self._say(said, "You already own this bot.")
            return
        if self._store.pair(said.person, code):
            self._store.remember_home(said.person, said.place)
            await self._say(
                said,
                "Paired. I follow the session running on this computer, and I write here when "
                "it needs your answer or finishes a long run. /mute turns that off. "
                "Add me to a group to share a session with it.",
            )
            await self._resolve(said)
        else:
            await self._say(
                said,
                "That code is not right or has expired. Get a new one in Chat apps in Plural's "
                "settings, or with `plural-host bridge pair`.",
            )

    async def _offer_rooms(self, place: Place, *, again: bool = False) -> None:
        running = self._rooms()
        if not running:
            await self._platform.show(
                place,
                self._key("link"),
                Notice(
                    "No session is running on the host's computer. "
                    "Start `plural` in a project folder, then send /link again."
                ),
            )
            return
        rows = tuple(
            (
                Choice(
                    f"{_project(entry)} · {entry.room[-6:]}",
                    f"link:{entry.room}",
                    Tone.PRIMARY,
                ),
            )
            for entry in running[:10]
        )
        current = self._store.room_of(place)
        note = f"\n\nNow following `{current}`." if current else ""
        if again:
            note += "\n\nThen write your message again."
        await self._platform.show(
            place,
            self._key("link"),
            Notice(f"**Which session should this chat follow?**{note}", rows),
        )

    async def _stop(self, place: Place) -> bool:
        room = self._store.room_of(place)
        if room is None:
            return False
        try:
            await self._feed(room).abort()
        except (ConnectionError, CommandRejected):
            return False
        return True

    def _status(self, place: Place) -> str:
        room = self._store.room_of(place)
        if room is None:
            return "This chat follows no session."
        feed = self._feeds.get(room)
        where = f" in `{feed.workspace}`" if feed and feed.workspace else ""
        state = "online" if feed and feed.online.is_set() else "offline"
        return f"This chat follows `{room}`{where}, {state}."

    # Buttons

    async def _pressed(self, pressed: Pressed) -> None:
        owner = self._store.is_owner(pressed.person)
        kind, _, rest = pressed.data.partition(":")
        if kind in {"ap", "link", "stop"} and not owner:
            await self._platform.answer(
                pressed, "Only the owner of this bot can do that.", alert=True
            )
            return
        match kind:
            case "ap":
                await self._approve(pressed, rest)
            case "link":
                self._store.link(pressed.place, rest)
                self._feed(rest)
                await self._platform.answer(pressed, "Linked.")
                entry = self._lookup(rest)
                where = f" in `{entry.workspace}`" if entry else ""
                await self._platform.show(
                    pressed.place,
                    self._key("linked"),
                    Notice(
                        f"This chat now follows `{rest}`{where}. Mention me to talk to the agent."
                    ),
                )
            case "stop":
                stopped = await self._stop(pressed.place)
                await self._platform.answer(pressed, "Stopping." if stopped else "Nothing to stop.")
            case _:
                await self._platform.answer(pressed)

    async def _approve(self, pressed: Pressed, rest: str) -> None:
        short, _, decision = rest.partition(":")
        found = self._book.find(short)
        if found is None:
            await self._platform.answer(pressed, "This request is already answered.")
            return
        room, approval_id = found
        try:
            await self._feed(room).decide(approval_id, ApprovalDecision(decision))
        except (ConnectionError, CommandRejected, ValueError) as error:
            await self._platform.answer(pressed, f"Could not answer: {error}"[:200], alert=True)
            return
        await self._platform.answer(pressed)

    async def _say(self, said: Said, text: str) -> None:
        await self._platform.show(said.place, self._key("say"), Notice(text), reply_to=said.ref)

    def _key(self, kind: str) -> str:
        """A key of its own for each of the bot's own messages, so none replaces another."""
        self._said_count += 1
        return f"{kind}:{self._said_count}"


def _project(entry: RunningRoom) -> str:
    return Path(entry.workspace).name or entry.workspace


_STRANGER = """This bot connects a chat to a Plural session.

If it is yours, open Chat apps in Plural's settings on the host's computer (or run \
`plural-host bridge pair`) and send me `/pair <code>` with the code it shows."""
