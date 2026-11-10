import asyncio
from collections import deque
from collections.abc import AsyncIterator, Iterable, Sequence

from plural.agent.providers.base import LlmEvent, LlmRequest, Stop, TextDelta, UsageReport
from plural.agent.providers.demo import reply, use_tool
from plural.protocol.models import Usage


class StallingProvider:
    def __init__(self, *, text: str = "") -> None:
        self.text = text

    async def stream(
        self, request: LlmRequest, *, cancel: asyncio.Event
    ) -> AsyncIterator[LlmEvent]:
        yield UsageReport(usage=Usage(input_tokens=7, output_tokens=3))
        if self.text:
            yield TextDelta(text=self.text)
        await asyncio.sleep(3600)
        yield Stop()


class Stall:
    pass


STALL = Stall()


class ScriptedProvider:
    def __init__(self, script: Sequence[Sequence[LlmEvent] | Exception | Stall]) -> None:
        self._script = deque(script)
        self.requests: list[LlmRequest] = []

    async def stream(
        self, request: LlmRequest, *, cancel: asyncio.Event
    ) -> AsyncIterator[LlmEvent]:
        self.requests.append(request)
        step = self._script.popleft()
        if isinstance(step, Exception):
            raise step
        if isinstance(step, Stall):
            await asyncio.sleep(3600)
            return
        for event in step:
            yield event


class FakeProvider:
    def __init__(self, script: Iterable[Sequence[LlmEvent]] = ()) -> None:
        self._turns: deque[tuple[LlmEvent, ...]] = deque(tuple(turn) for turn in script)
        self.requests: list[LlmRequest] = []

    def enqueue(self, *turns: Sequence[LlmEvent]) -> None:
        self._turns.extend(tuple(turn) for turn in turns)

    async def stream(
        self, request: LlmRequest, *, cancel: asyncio.Event
    ) -> AsyncIterator[LlmEvent]:
        self.requests.append(request)
        turn = self._turns.popleft() if self._turns else reply("Done.")
        for event in turn:
            if cancel.is_set():
                return
            await asyncio.sleep(0)
            yield event


__all__ = ["STALL", "FakeProvider", "ScriptedProvider", "StallingProvider", "reply", "use_tool"]
