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

import structlog

from plural.bridge.model import Choice, Notice, Place, Pressed, Said, Tone
from plural.bridge.platform import ChatPlatform
from plural.bridge.room import ApprovalBook, RoomFeed
from plural.bridge.store import BridgeStore
from plural.client.connection import CommandRejected
from plural.protocol.commands import ClientInfo
from plural.protocol.models import ApprovalDecision
from plural.protocol.running import RunningRoom

log = structlog.get_logger(__name__)

HELP = """**Plural in this chat**

Mention me or reply to me to talk to the agent of the linked session.

/link: pick a session running on the host's computer for this chat
/unlink: stop following it here
/status: which session this chat follows
/stop: stop the agent's current run
/ask <text>: send a prompt without a mention

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
    ) -> None:
        self._platform = platform
        self._store = store
        self._rooms = rooms
        self._client = client
        self._book = ApprovalBook()
        self._feeds: dict[str, RoomFeed] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._said_count = 0

    async def run(self) -> None:
        await self._platform.start()
        for room in self._store.rooms:
            self._feed(room)
        try:
            async for item in self._platform.incoming():
                try:
                    match item:
                        case Said():
                            await self._said(item)
                        case Pressed():
                            await self._pressed(item)
                except Exception:
                    log.exception("bridge.handle_failed")
        finally:
            await self.close()

    async def close(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        for room, task in list(self._tasks.items()):
            with suppress(asyncio.CancelledError, Exception):
                await task
            await self._feeds[room].close()
        self._tasks.clear()
        self._feeds.clear()

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
            )
            self._tasks[room] = asyncio.create_task(feed.run(), name=f"room:{room}")
        return feed

    def _lookup(self, room: str) -> RunningRoom | None:
        return next((entry for entry in self._rooms() if entry.room == room), None)

    # Messages

    async def _said(self, said: Said) -> None:
        if not said.addressed:
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
                if said.place.private and not owner:
                    await self._say(said, _STRANGER)
                else:
                    await self._say(said, HELP)
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
            case "link" | "unlink" | "stop":
                await self._say(said, "Only the owner of this bot can do that.")
            case _:
                pass

    async def _prompt(self, said: Said, text: str) -> None:
        if not text.strip():
            await self._say(
                said, "Write something after the command, or mention me with a question."
            )
            return
        room = self._store.room_of(said.place)
        if room is None:
            owner = self._store.is_owner(said.person)
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

    async def _pair(self, said: Said, code: str) -> None:
        if not said.place.private:
            await self._say(said, "Pair in a private chat with me, so nobody else sees the code.")
            return
        if self._store.is_owner(said.person):
            await self._say(said, "You already own this bot.")
            return
        if self._store.pair(said.person, code):
            await self._say(
                said, "Paired. Add me to a group, or stay here, and send /link to pick a session."
            )
        else:
            await self._say(
                said, "That code is not right. The runner of the bridge prints it at start."
            )

    async def _offer_rooms(self, place: Place) -> None:
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
                    f"{Path(entry.workspace).name or entry.workspace} · {entry.room[-6:]}",
                    f"link:{entry.room}",
                    Tone.PRIMARY,
                ),
            )
            for entry in running[:10]
        )
        current = self._store.room_of(place)
        note = f"\n\nNow following `{current}`." if current else ""
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


_STRANGER = """This bot connects a chat to a Plural session.

If it is yours, run `plural-host bridge telegram` on the host's computer and send me \
`/pair <code>` with the code it prints."""
