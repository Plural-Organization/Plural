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
    room_ttl_s: float = 900.0
    max_rooms_per_peer: int = 3
    max_guests_per_peer: int = 30
    connects_per_second: float = 2.0
    connect_burst: int = 20


class TokenBucket:
    def __init__(
        self, rate: float, burst: int, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._rate = rate
        self._burst = burst
        self._clock = clock
        self._tokens = float(burst)
        self._updated = clock()

    def full(self) -> bool:
        refilled = self._tokens + (self._clock() - self._updated) * self._rate
        return refilled >= self._burst

    def take(self) -> bool:
        now = self._clock()
        self._tokens = min(self._burst, self._tokens + (now - self._updated) * self._rate)
        self._updated = now
        if self._tokens < 1:
            return False
        self._tokens -= 1
        return True


@dataclass(slots=True)
class _Peer:
    bucket: TokenBucket
    hosts: int = 0
    guests: int = 0

    def idle(self) -> bool:
        return self.hosts == 0 and self.guests == 0 and self.bucket.full()


class PeerGate:
    def __init__(self, limits: RelayLimits, clock: Callable[[], float] = time.monotonic) -> None:
        self._limits = limits
        self._clock = clock
        self._peers: dict[str, _Peer] = {}

    def admit(self, peer: str, *, host: bool) -> bool:
        if len(self._peers) >= _PRUNE_ABOVE:
            self._peers = {key: value for key, value in self._peers.items() if not value.idle()}
        entry = self._peers.get(peer)
        if entry is None:
            bucket = TokenBucket(
                self._limits.connects_per_second, self._limits.connect_burst, self._clock
            )
            entry = self._peers[peer] = _Peer(bucket)
        if not entry.bucket.take():
            return False
        if host:
            if entry.hosts >= self._limits.max_rooms_per_peer:
                return False
            entry.hosts += 1
        else:
            if entry.guests >= self._limits.max_guests_per_peer:
                return False
            entry.guests += 1
        return True

    def release(self, peer: str, *, host: bool) -> None:
        entry = self._peers.get(peer)
        if entry is None:
            return
        if host:
            entry.hosts = max(0, entry.hosts - 1)
        else:
            entry.guests = max(0, entry.guests - 1)


_PRUNE_ABOVE = 1024
