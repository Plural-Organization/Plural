import os
import time
from datetime import UTC, datetime
from typing import Final

_CROCKFORD: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class UlidGenerator:
    def new(self, prefix: str) -> str:
        return f"{prefix}{ulid(time.time_ns() // 1_000_000, os.urandom(10))}"


def ulid(timestamp_ms: int, randomness: bytes) -> str:
    value = (timestamp_ms << 80) | int.from_bytes(randomness)
    return "".join(_CROCKFORD[(value >> (5 * i)) & 31] for i in reversed(range(26)))
