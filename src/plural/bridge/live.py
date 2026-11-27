"""A message that is changed while the agent works, for any chat service.

A run is shown as one message that is edited as the agent goes. Services limit how often a message
may change, so a view that is not final waits for its turn (and a newer one replaces it while it
waits), but a final view always goes through. Each service says how to put a view on screen.
"""

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final

import structlog

from plural.bridge.model import Answer, Notice, Place
from plural.bridge.platform import PlatformError

log = structlog.get_logger(__name__)

REMEMBERED: Final = 500


@dataclass(slots=True)
class Slot:
    """What a service remembers about one message it sent."""

    message_id: Any = None
    sent: str = ""
    at: float = 0.0
    later: asyncio.Task[None] | None = None
    pending: tuple[Answer | Notice, str | None] | None = None


type Put = Callable[[Place, Slot, Answer | Notice, bool, str | None], Awaitable[None]]


class LiveMessages:
    def __init__(
        self,
        put: Put,
        *,
        every: Callable[[Place, Answer | Notice], float],
        retry_after: Callable[[PlatformError], float | None] = lambda _error: None,
    ) -> None:
        self._put = put
        self._every = every
        self._retry_after = retry_after
        self._slots: OrderedDict[tuple[str, str], Slot] = OrderedDict()
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    async def show(
        self,
        place: Place,
        key: str,
        view: Answer | Notice,
        *,
        final: bool = True,
        reply_to: str | None = None,
    ) -> None:
        slot_key = (place.key, key)
        lock = self._locks.setdefault(slot_key, asyncio.Lock())
        slot = self._slots.get(slot_key) or Slot()
        self._remember(slot_key, slot)
        every = self._every(place, view)
        if not final:
            wait = slot.at + every - time.monotonic()
            if wait > 0 or lock.locked():
                slot.pending = (view, reply_to)
                if slot.later is None or slot.later.done():
                    slot.later = asyncio.create_task(self._later(place, key, max(wait, 0.2)))
                return
        else:
            slot.pending = None
            if slot.later is not None:
                slot.later.cancel()
                slot.later = None
        async with lock:
            if final:
                wait = slot.at + every - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
            try:
                await self._put(place, slot, view, final, reply_to)
            except PlatformError as error:
                if not final:
                    log.info("bridge.update_skipped", error=str(error))
                    return
                delay = self._retry_after(error)
                if not delay:
                    raise
                await asyncio.sleep(delay)
                await self._put(place, slot, view, final, reply_to)
            finally:
                slot.at = time.monotonic()
        if final and isinstance(view, Answer):
            self._slots.pop(slot_key, None)
            self._locks.pop(slot_key, None)

    async def _later(self, place: Place, key: str, wait: float) -> None:
        await asyncio.sleep(wait)
        slot = self._slots.get((place.key, key))
        if slot is None or slot.pending is None:
            return
        view, reply_to = slot.pending
        slot.pending = None
        slot.later = None
        await self.show(place, key, view, final=False, reply_to=reply_to)

    async def close(self) -> None:
        for slot in self._slots.values():
            if slot.later is not None:
                slot.later.cancel()

    def _remember(self, slot_key: tuple[str, str], slot: Slot) -> None:
        self._slots[slot_key] = slot
        self._slots.move_to_end(slot_key)
        while len(self._slots) > REMEMBERED:
            old, dropped = self._slots.popitem(last=False)
            self._locks.pop(old, None)
            if dropped.later is not None:
                dropped.later.cancel()
