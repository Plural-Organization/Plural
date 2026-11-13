import asyncio
import itertools
from collections.abc import AsyncGenerator, AsyncIterator

import structlog

from plural.agent.loop.interrupt import Interrupted, interruptible
from plural.agent.providers.base import (
    LlmEvent,
    LLMProvider,
    LlmRequest,
    ProviderActivity,
    ProviderBusy,
    ProviderError,
)

log = structlog.get_logger(__name__)


class ResilientProvider:
    """Retries a busy provider before it streams and fails a stream that goes silent."""

    def __init__(
        self,
        inner: LLMProvider,
        *,
        first_token_timeout_s: float,
        idle_timeout_s: float,
        retries: int,
        retry_delay_s: float,
    ) -> None:
        self.inner = inner
        self._first_token_timeout_s = first_token_timeout_s
        self._idle_timeout_s = idle_timeout_s
        self._retries = retries
        self._retry_delay_s = retry_delay_s

    async def close(self) -> None:
        close = getattr(self.inner, "close", None)
        if close is not None:
            await close()

    async def stream(
        self, request: LlmRequest, *, cancel: asyncio.Event
    ) -> AsyncIterator[LlmEvent]:
        for attempt in itertools.count():
            started = False
            try:
                async for event in self._attempt(request, cancel):
                    started = True
                    yield event
                return
            except ProviderBusy as error:
                if started or attempt >= self._retries:
                    raise
                delay = self._retry_delay_s * 2**attempt
                log.warning(
                    "agent.provider_busy", error=str(error), attempt=attempt + 1, delay=delay
                )
                try:
                    await interruptible(asyncio.sleep(delay), cancel)
                except Interrupted:
                    return

    async def _attempt(self, request: LlmRequest, cancel: asyncio.Event) -> AsyncIterator[LlmEvent]:
        stream = self.inner.stream(request, cancel=cancel).__aiter__()
        limit = self._first_token_timeout_s
        event_count = 0
        last_event_kind: str | None = None
        # One wait on the cancel event for the whole stream: a fast model sends hundreds of
        # events a second, and a new task per event for it was most of this wrapper's cost.
        stop = asyncio.create_task(cancel.wait())
        try:
            while True:
                step = asyncio.ensure_future(anext(stream))
                try:
                    await asyncio.wait(
                        {step, stop}, timeout=limit, return_when=asyncio.FIRST_COMPLETED
                    )
                finally:
                    if not step.done():
                        step.cancel()
                        await asyncio.gather(step, return_exceptions=True)
                if step.cancelled():
                    if stop.done():
                        return
                    log.warning(
                        "agent.provider_timeout",
                        provider=type(self.inner).__name__,
                        timeout_s=limit,
                        events_received=event_count,
                        last_event_kind=last_event_kind,
                    )
                    raise ProviderError(f"model produced no output for {limit:g}s") from None
                try:
                    event = step.result()
                except StopAsyncIteration:
                    return
                event_count += 1
                last_event_kind = event.kind
                if isinstance(event, ProviderActivity):
                    last_event_kind = event.source
                    continue
                limit = self._idle_timeout_s
                yield event
        finally:
            stop.cancel()
            await asyncio.gather(stop, return_exceptions=True)
            if isinstance(stream, AsyncGenerator):
                await stream.aclose()
