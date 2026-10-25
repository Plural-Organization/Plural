import asyncio
from collections.abc import AsyncIterator

from plural.agent.providers.base import LlmEvent, LlmRequest, Stop, TextDelta, UsageReport
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
