"""The models a loop calls: the main one, and a cheaper helper for summaries, briefings and side
questions. Each is wrapped to retry when busy and to fail when silent; every request can be dumped,
and what each model spends is counted by who it was for."""

import asyncio
from collections.abc import AsyncIterator, Callable

import structlog

from plural.agent.context.compaction import CompactionFailed, extract_tagged
from plural.agent.context.telemetry import RequestDump, observed
from plural.agent.loop.events import Spend
from plural.agent.providers.base import (
    LlmEvent,
    LLMProvider,
    LlmRequest,
    ProviderError,
    Stop,
    TextDelta,
    ToolCallReady,
    UsageReport,
)
from plural.agent.providers.resilient import ResilientProvider
from plural.protocol.models import Usage

log = structlog.get_logger(__name__)


class AskFailed(Exception):
    pass


class Models:
    def __init__(
        self,
        main: LLMProvider,
        helper: LLMProvider | None,
        *,
        wrap: Callable[[LLMProvider], ResilientProvider],
        dump: RequestDump | None,
    ) -> None:
        self._wrap = wrap
        self.dump = dump
        self.main = wrap(main)
        self.helper = wrap(helper) if helper is not None else None
        self._spending: dict[tuple[str, str], Spend] = {}
        self._closing: set[asyncio.Task[None]] = set()

    def swap(self, main: LLMProvider, helper: LLMProvider | None) -> None:
        """Use other models from the next request on; the ones left go are closed meanwhile."""
        retired = [wrapper.inner for wrapper in (self.main, self.helper) if wrapper]
        self.main = self._wrap(main)
        self.helper = self._wrap(helper) if helper is not None else None
        for previous in retired:
            close = getattr(previous, "close", None)
            if close is not None and previous not in (main, helper):
                task = asyncio.create_task(close())
                self._closing.add(task)
                task.add_done_callback(self._closing.discard)

    async def close(self) -> None:
        close = getattr(self.main, "close", None)
        if close is not None:
            await close()
        if self._closing:
            await asyncio.gather(*self._closing, return_exceptions=True)

    def role(self, provider: LLMProvider) -> str:
        return "fast" if provider is self.helper else "main"

    def spend(self, role: str, who: str, usage: Usage, *, uses: int = 0) -> None:
        key = (role, who)
        previous = self._spending.get(key, Spend(role, who, Usage(), 0))
        self._spending[key] = Spend(role, who, previous.usage + usage, previous.uses + uses)

    def take_spending(self) -> tuple[Spend, ...]:
        spending = tuple(
            spend
            for spend in self._spending.values()
            if spend.uses or spend.usage.prompt_tokens or spend.usage.output_tokens
        )
        self._spending = {}
        return spending

    def stream(
        self,
        request: LlmRequest,
        cancel: asyncio.Event,
        provider: LLMProvider | None = None,
        *,
        purpose: str = "turn",
    ) -> AsyncIterator[LlmEvent]:
        """One request to a model, the main one unless named, dumped and logged."""
        chosen = provider or self.main
        dumped = self.dump.write(request, purpose) if self.dump is not None else None
        return observed(
            chosen.stream(request, cancel=cancel),
            request,
            purpose=purpose,
            role=self.role(chosen),
            dumped=dumped,
        )

    async def tagged(
        self,
        request: LlmRequest,
        cancel: asyncio.Event,
        *,
        tag: str,
        purpose: str,
        counted: Callable[[Usage], None] | None = None,
    ) -> tuple[str, str]:
        """The text in `<tag>` of a model's answer, and which model wrote it: the helper first,
        the main model when the helper fails. `counted` gets each usage report, for a caller that
        counts what its own work spent."""
        for provider in (self.helper, self.main):
            if provider is None:
                continue
            try:
                text = await self._tagged(request, provider, cancel, tag, purpose, counted)
            except CompactionFailed as error:
                if cancel.is_set() or provider is self.main:
                    raise
                what = "compaction" if purpose == "compact" else purpose
                log.warning(f"agent.helper_{what}_failed", error=str(error))
                continue
            role = self.role(provider)
            self.spend(role, purpose, Usage(), uses=1)
            return text, role
        raise CompactionFailed("no model is available")

    async def _tagged(
        self,
        request: LlmRequest,
        provider: LLMProvider,
        cancel: asyncio.Event,
        tag: str,
        purpose: str,
        counted: Callable[[Usage], None] | None,
    ) -> str:
        text: list[str] = []
        called = False
        cut_off = False
        role = self.role(provider)
        try:
            async for event in self.stream(request, cancel, provider, purpose=purpose):
                match event:
                    case TextDelta(text=chunk):
                        text.append(chunk)
                    case ToolCallReady():
                        called = True
                    case Stop(reason="max_tokens"):
                        cut_off = True
                    case UsageReport(usage=delta):
                        if counted is not None:
                            counted(delta)
                        self.spend(role, purpose, delta)
                    case _:
                        pass
        except ProviderError as error:
            raise CompactionFailed(str(error)) from error
        found = extract_tagged("".join(text), tag)
        if cut_off:
            raise CompactionFailed("the summary was cut off at the output limit")
        if cancel.is_set() or called or not found:
            raise CompactionFailed("the model did not produce a summary")
        return found

    async def answer(self, request: LlmRequest, cancel: asyncio.Event, *, main: bool) -> str:
        """A plain text answer, from the helper first unless `main` asks for the main model."""
        providers = [self.main] if main else [p for p in (self.helper, self.main) if p]
        for provider in providers:
            role = self.role(provider)
            text: list[str] = []
            try:
                async for event in self.stream(request, cancel, provider, purpose="ask"):
                    match event:
                        case TextDelta(text=chunk):
                            text.append(chunk)
                        case UsageReport(usage=delta):
                            self.spend(role, "plugin", delta)
                        case _:
                            pass
            except ProviderError as error:
                if cancel.is_set() or provider is self.main:
                    raise AskFailed(str(error)) from error
                log.warning("agent.helper_ask_failed", error=str(error))
                continue
            self.spend(role, "plugin", Usage(), uses=1)
            reply = "".join(text).strip()
            if not reply:
                raise AskFailed("the model gave no answer")
            return reply
        raise AskFailed("no model is available")
