"""What each model call cost and how long it took, written to the host log.

Every call ends in one `llm.call` line: the tokens it was billed, how much of the prompt the
provider served from its cache, the time to the first output and in all. With a `RequestDump`,
the request itself is saved too, so what the model saw can be read back after the fact.
"""

import json
import time
from collections.abc import AsyncIterator
from pathlib import Path

import structlog

from plural.agent.providers.base import (
    LlmEvent,
    LlmRequest,
    Stop,
    TextDelta,
    ThinkingDelta,
    ToolCallReady,
    UsageReport,
)
from plural.agent.tracing import Span
from plural.protocol.models import SpanStatus, Usage

log = structlog.get_logger(__name__)


def hit_rate(usage: Usage) -> float | None:
    """The share of the prompt read from the provider's cache, or None without a prompt."""
    prompt = usage.prompt_tokens
    return round(usage.cache_read_tokens / prompt, 3) if prompt else None


class RequestDump:
    """Saves each request the loop sends as numbered JSON, images left out."""

    def __init__(self, folder: Path) -> None:
        self._folder = folder
        self._count: int | None = None

    def write(self, request: LlmRequest, purpose: str) -> Path:
        self._folder.mkdir(parents=True, exist_ok=True)
        if self._count is None:
            # A host that restarts in the same room goes on numbering instead of overwriting.
            self._count = sum(1 for _ in self._folder.glob("*.json"))
        self._count += 1
        path = self._folder / f"{self._count:05d}-{purpose}.json"
        data = request.model_dump(mode="json", exclude_none=True)
        for message in data["messages"]:
            for image in message.get("images", ()):
                image["data"] = f"<{len(image['data'])} base64 characters>"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return path


_STATUS = {"ok": SpanStatus.OK, "error": SpanStatus.ERROR, "cancelled": SpanStatus.CANCELLED}


async def observed(
    events: AsyncIterator[LlmEvent],
    request: LlmRequest,
    *,
    purpose: str,
    role: str,
    dumped: Path | None = None,
    span: Span | None = None,
) -> AsyncIterator[LlmEvent]:
    """Pass a model call's events through; log what it cost, and close its span, once it ends."""
    started = time.monotonic()
    first: float | None = None
    usage = Usage()
    stop: str | None = None
    outcome = "cancelled"
    # The prompt of the call's last request: the context the conversation filled then.
    context = 0
    failure = ""
    try:
        async for event in events:
            match event:
                case TextDelta() | ThinkingDelta() | ToolCallReady() if first is None:
                    first = time.monotonic()
                case UsageReport(usage=delta, last=last):
                    usage = usage + delta
                    context = (last or delta).prompt_tokens or context
                case Stop(reason=reason):
                    stop = reason
                case _:
                    pass
            yield event
        outcome = "ok"
    except Exception as error:
        outcome = "error"
        failure = str(error)
        raise
    finally:
        first_ms = round((first - started) * 1000) if first is not None else None
        if span is not None:
            span.end(
                _STATUS[outcome],
                usage=usage,
                context_tokens=context,
                first_ms=first_ms,
                error=failure[:300],
            )
        log.info(
            "llm.call",
            purpose=purpose,
            role=role,
            outcome=outcome,
            stop=stop,
            messages=len(request.messages),
            tools=len(request.tools),
            input=usage.input_tokens,
            cache_read=usage.cache_read_tokens,
            cache_write=usage.cache_write_tokens,
            output=usage.output_tokens,
            hit=hit_rate(usage),
            first_ms=first_ms,
            total_ms=round((time.monotonic() - started) * 1000),
            request=str(dumped) if dumped is not None else None,
        )
