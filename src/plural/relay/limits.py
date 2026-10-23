import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RelayLimits:
    max_message_bytes: int = 4 * 1024 * 1024
    max_guests_per_room: int = 10
    max_rooms: int = 50
    guest_queue: int = 512
    host_queue: int = 4096
    messages_per_second: float = 20.0
    burst: int = 40


class TokenBucket:
    def __init__(
        self, rate: float, burst: int, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._rate = rate
        self._burst = burst
        self._clock = clock
        self._tokens = float(burst)
        self._updated = clock()

    def take(self) -> bool:
        now = self._clock()
        self._tokens = min(self._burst, self._tokens + (now - self._updated) * self._rate)
        self._updated = now
        if self._tokens < 1:
            return False
        self._tokens -= 1
        return True
