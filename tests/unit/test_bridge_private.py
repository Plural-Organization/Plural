"""The owner's private chat: pairing by link, no /link to type, and /mute."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

from plural.bridge.bridge import Bridge
from plural.bridge.model import Answer, Incoming, Notice, Person, Place, Pressed, Said
from plural.bridge.platform import Links
from plural.bridge.store import BridgeStore
from plural.protocol.commands import ClientInfo
from plural.protocol.running import RunningRoom

DM = Place("fake", "10", None, private=True)
GROUP = Place("fake", "-1", None, private=False)
ME = Person("10", "Tamirlan")
STRANGER = Person("99", "Askar")


class Chat:
    name = "fake"
    identity = "@fake"
    links = Links()

    def __init__(self) -> None:
        self.told: list[Notice] = []

    async def start(self) -> None:
        return None

    async def incoming(self) -> AsyncIterator[Incoming]:
        for _ in ():
            yield _

    async def show(
        self,
        place: Place,
        key: str,
        view: Answer | Notice,
        *,
        final: bool = True,
        reply_to: str | None = None,
    ) -> None:
        if isinstance(view, Notice):
            self.told.append(view)

    async def answer(self, pressed: Pressed, text: str = "", *, alert: bool = False) -> None:
        return None

    async def close(self) -> None:
        return None

    @property
    def last(self) -> str:
        return self.told[-1].text if self.told else ""


def room(name: str) -> RunningRoom:
    return RunningRoom(
        room=f"room-{name}",
        host_link="plural://unused",
        workspace=f"/work/{name}",
        pid=1,
        started_at=datetime.now(UTC),
    )


def setup(tmp_path: Path, rooms: list[RunningRoom]) -> tuple[Bridge, Chat, BridgeStore]:
    chat = Chat()
    store = BridgeStore(tmp_path, "fake")
    bridge = Bridge(chat, store, rooms=lambda: rooms, client=ClientInfo(kind="test", version="0"))
    return bridge, chat, store


async def say(bridge: Bridge, person: Person, place: Place, text: str) -> None:
    await bridge._said(Said(place, person, text, addressed=True))  # pyright: ignore[reportPrivateUsage]


async def test_start_with_the_code_from_the_link_makes_the_person_an_owner(tmp_path: Path) -> None:
    bridge, chat, store = setup(tmp_path, [])
    code = store.pairing_code()

    await say(bridge, ME, DM, f"/start {code}")

    assert store.is_owner(ME)
    assert store.alert_places() == [DM]
    assert "Paired" in chat.told[0].text
    assert "No session is running" in chat.last


async def test_start_with_a_wrong_code_does_not_pair(tmp_path: Path) -> None:
    bridge, chat, store = setup(tmp_path, [])
    store.pairing_code()

    await say(bridge, STRANGER, DM, "/start 000000")

    assert not store.is_owner(STRANGER)
    assert "not right" in chat.last


async def test_an_owner_with_nothing_running_is_told_to_start_a_session(tmp_path: Path) -> None:
    bridge, chat, store = setup(tmp_path, [])
    store.pair(ME, store.pairing_code())

    await say(bridge, ME, DM, "what changed?")

    assert "No session is running" in chat.last
    assert store.room_of(DM) is None


async def test_several_running_sessions_are_offered_instead_of_guessing(tmp_path: Path) -> None:
    bridge, chat, store = setup(tmp_path, [room("a"), room("b")])
    store.pair(ME, store.pairing_code())

    await say(bridge, ME, DM, "what changed?")

    offered = chat.told[-1]
    assert "write your message again" in offered.text
    assert [row[0].data for row in offered.choices] == ["link:room-a", "link:room-b"]
    assert store.room_of(DM) is None


async def test_a_private_chat_forgets_a_stopped_session_before_offering_the_running_ones(
    tmp_path: Path,
) -> None:
    bridge, chat, store = setup(tmp_path, [room("a"), room("b")])
    store.pair(ME, store.pairing_code())
    store.link(DM, "room-gone")

    await say(bridge, ME, DM, "what changed?")

    offered = chat.told[-1]
    assert "write your message again" in offered.text
    assert [row[0].data for row in offered.choices] == ["link:room-a", "link:room-b"]
    assert store.room_of(DM) is None


async def test_a_group_is_never_linked_by_itself(tmp_path: Path) -> None:
    bridge, chat, store = setup(tmp_path, [room("a")])
    store.pair(ME, store.pairing_code())

    await say(bridge, ME, GROUP, "what changed?")

    assert store.room_of(GROUP) is None
    assert "/link" in chat.last


async def test_a_stranger_in_a_private_chat_is_not_followed_anywhere(tmp_path: Path) -> None:
    bridge, _chat, store = setup(tmp_path, [room("a")])
    store.pair(ME, store.pairing_code())

    await say(bridge, STRANGER, DM, "hello")

    assert store.room_of(DM) is None
    assert store.alert_places() == []


async def test_mute_stops_alerts_and_unmute_brings_them_back(tmp_path: Path) -> None:
    bridge, chat, store = setup(tmp_path, [])
    store.pair(ME, store.pairing_code())
    await say(bridge, ME, DM, "/help")
    assert store.alert_places() == [DM]

    await say(bridge, ME, DM, "/mute")
    assert store.alert_places() == []
    assert "Muted" in chat.last

    await say(bridge, ME, DM, "/unmute")
    assert store.alert_places() == [DM]


async def test_mute_before_any_private_chat_asks_for_one(tmp_path: Path) -> None:
    bridge, chat, store = setup(tmp_path, [])
    store.pair(ME, store.pairing_code())

    await say(bridge, ME, GROUP, "/mute")

    assert "private chat first" in chat.last


async def test_a_stranger_cannot_mute(tmp_path: Path) -> None:
    bridge, chat, store = setup(tmp_path, [])
    store.pair(ME, store.pairing_code())

    await say(bridge, STRANGER, DM, "/mute")

    assert "Only the owner" in chat.last


def test_unpairing_forgets_the_private_chat(tmp_path: Path) -> None:
    store = BridgeStore(tmp_path, "fake")
    store.pair(ME, store.pairing_code())
    store.remember_home(ME, DM)

    store.unpair(ME.id)

    assert store.alert_places() == []
