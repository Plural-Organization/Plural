import time
from collections.abc import Callable
from typing import Final

MAX_STREAMED_CHARS: Final = 64_000
MAX_BATCH_LINES: Final = 50
MIN_INTERVAL_S: Final = 0.1


class LineStream:
    def __init__(
        self, emit: Callable[[str], None], *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._emit = emit
        self._clock = clock
        self._partial = ""
        self._ready: list[str] = []
        self._streamed = 0
        self._last = clock()

    def feed(self, text: str) -> None:
        self._partial += text
        *lines, self._partial = self._partial.split("\n")
        self._ready.extend(f"{line}\n" for line in lines)
        if len(self._ready) >= MAX_BATCH_LINES or self._clock() - self._last >= MIN_INTERVAL_S:
            self.flush()

    def flush(self) -> None:
        if not self._ready:
            return
        batch = "".join(self._ready)
        self._ready = []
        self._last = self._clock()
        remaining = MAX_STREAMED_CHARS - self._streamed
        if remaining <= 0:
            return
        batch = batch[:remaining]
        self._streamed += len(batch)
        self._emit(batch)
