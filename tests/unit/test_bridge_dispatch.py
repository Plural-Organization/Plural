import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from plural.bridge.bridge import Bridge
from plural.bridge.model import Answer, Incoming, Notice, Person, Place, Pressed, Said
from plural.bridge.store import BridgeStore
from plural.protocol.commands import ClientInfo

PLACE = Place("fake", "1")
OTHER = Place("fake", "2")
PERSON = Person("1", "Askar")


class Chat:
    name = "fake"
    identity = "@fake"

    def __init__(self) -> None:
        self.inbox: asyncio.Queue[Incoming] = asyncio.Queue()
        self.answered: list[str] = []
        self.told: list[str] = []

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
        if isinstance(view, Notice):
            self.told.append(f"{place.chat}:{view.text}")

    async def answer(self, pressed: Pressed, text: str = "", *, alert: bool = False) -> None:
        self.answered.append(pressed.data)

    async def close(self) -> None:
        return None


async def test_a_slow_message_does_not_hold_up_a_button_or_another_chat(tmp_path: Path) -> None:
    chat = Chat()
    bridge = Bridge(
        chat,
        BridgeStore(tmp_path, "fake"),
        rooms=lambda: [],
        client=ClientInfo(kind="test", version="0"),
    )
    gate = asyncio.Event()
    original = bridge._said  # pyright: ignore[reportPrivateUsage]

    async def slow(said: Said) -> None:
        if said.text == "slow":
            await gate.wait()
        await original(said)

    bridge._said = slow  # type: ignore[method-assign]  # pyright: ignore[reportPrivateUsage]
    running = asyncio.create_task(bridge.run())
    try:
        await chat.inbox.put(Said(PLACE, PERSON, "slow", addressed=True))
        await chat.inbox.put(Pressed(PLACE, PERSON, "whatever"))
        await chat.inbox.put(Said(OTHER, PERSON, "/status", addressed=True))

        async with asyncio.timeout(3):
            while not (chat.answered and chat.told):
                await asyncio.sleep(0.01)
        # The slow message is still waiting, and the others were answered.
        assert chat.answered == ["whatever"]
        assert chat.told == ["2:This chat follows no session."]
    finally:
        gate.set()
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)


async def test_talk_in_one_chat_is_handled_in_order(tmp_path: Path) -> None:
    chat = Chat()
    bridge = Bridge(
        chat,
        BridgeStore(tmp_path, "fake"),
        rooms=lambda: [],
        client=ClientInfo(kind="test", version="0"),
    )
    seen: list[str] = []

    async def record(said: Said) -> None:
        await asyncio.sleep(0.05 if said.text == "first" else 0)
        seen.append(said.text)

    bridge._said = record  # type: ignore[method-assign]  # pyright: ignore[reportPrivateUsage]
    running = asyncio.create_task(bridge.run())
    try:
        await chat.inbox.put(Said(PLACE, PERSON, "first", addressed=True))
        await chat.inbox.put(Said(PLACE, PERSON, "second", addressed=True))
        async with asyncio.timeout(3):
            while len(seen) < 2:
                await asyncio.sleep(0.01)
    finally:
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)

    assert seen == ["first", "second"]
