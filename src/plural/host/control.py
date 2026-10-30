import asyncio
import json
import time
from collections.abc import Callable, Coroutine
from typing import Any, Final, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from plural.agent.providers.base import (
    LlmMessage,
    LLMProvider,
    LlmRequest,
    ProviderError,
    Stop,
    TextDelta,
)
from plural.agent.providers.cli.codex_cli import CodexCliProvider
from plural.core.errors import DomainError
from plural.host.bootstrap import Host, build_web_search
from plural.host.config import HostSettings
from plural.host.inbox import Reconfigure
from plural.host.providers import ConfigError, build_provider, provider_secrets, resolve_api_key
from plural.host.routing import build_helper

log = structlog.get_logger(__name__)

PROBE_TIMEOUT_S: Final = 30.0
PROBE_PROMPT: Final = "Reply with the single word ok."
MAX_LINE_BYTES: Final = 64 * 1024


class AgentConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    provider: Literal["fake", "anthropic", "anthropic_oauth", "claude_code", "codex_cli", "openai"]
    provider_name: str | None = Field(default=None, max_length=64)
    model: str | None = None
    base_url: str | None = None
    api_key: SecretStr | None = None
    context_window: int | None = Field(default=None, gt=0)
    fast_model: str | None = Field(default=None, max_length=200)


class Request(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str
    type: Literal["configure", "test"]
    config: AgentConfig


Reply = Callable[[dict[str, object]], None]


def settings_for(base: HostSettings, config: AgentConfig) -> HostSettings:
    return base.model_copy(
        update={
            "provider": config.provider,
            "model": config.model or None,
            "base_url": config.base_url or None,
            "api_key": config.api_key,
            "context_window": config.context_window or base.context_window,
            "fast_model": config.fast_model
            if config.fast_model not in (None, "", "off")
            else base.fast_model,
            "fast_provider": None
            if config.fast_model not in (None, "", "off")
            else base.fast_provider,
        }
    )


def provider_for(
    base: HostSettings, config: AgentConfig
) -> tuple[LLMProvider, HostSettings, str | None]:
    settings = settings_for(base, config)
    key = resolve_api_key(settings, {})
    return build_provider(settings, key), settings, key


async def probe(provider: LLMProvider) -> str:
    request = LlmRequest(
        system="You are a coding assistant.",
        messages=(LlmMessage(role="user", content=PROBE_PROMPT),),
    )
    started = time.monotonic()
    cancel = asyncio.Event()

    async def consume() -> None:
        async for event in provider.stream(request, cancel=cancel):
            if isinstance(event, TextDelta | Stop):
                return

    try:
        await asyncio.wait_for(consume(), PROBE_TIMEOUT_S)
    except TimeoutError:
        raise ProviderError(f"no answer within {PROBE_TIMEOUT_S:g}s") from None
    return f"answered in {time.monotonic() - started:.1f}s"


class Control:
    def __init__(self, host: Host, base: HostSettings, reply: Reply) -> None:
        self._host = host
        self._base = base
        self._reply = reply

    async def handle(self, line: str) -> None:
        request = self._parse(line)
        if request is None:
            return
        try:
            if request.type == "test":
                provider, _, _ = provider_for(self._base, request.config)
                message = await probe(provider)
                self._reply({"type": "result", "id": request.id, "ok": True, "message": message})
            else:
                label = await self._configure(request.config)
                self._reply({"type": "result", "id": request.id, "ok": True, "agent": label})
        except (ConfigError, ProviderError, DomainError) as error:
            self._reply({"type": "result", "id": request.id, "ok": False, "error": str(error)})
        except Exception:
            log.exception("control.failed", request=request.type)
            self._reply(
                {"type": "result", "id": request.id, "ok": False, "error": "internal error"}
            )

    async def _configure(self, config: AgentConfig) -> str:
        provider, settings, key = provider_for(self._base, config)
        if isinstance(provider, CodexCliProvider):
            await provider.check_available()
        searcher = build_web_search(settings, key, provider)
        done: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        label = (
            f"{config.provider_name} · {settings.model or 'default'}"
            if config.provider_name and config.provider != "fake"
            else settings.agent_label({})
        )
        helper = None if config.fast_model == "off" else build_helper(settings)
        self._host.inbox.put(
            Reconfigure(
                provider=provider,
                label=label,
                context_window=settings.context_window,
                secrets=(*provider_secrets(settings, key), *(helper.secrets if helper else ())),
                reply=done,
                helper=helper.provider if helper else None,
                helper_label=helper.label if helper else "",
            )
        )
        await done
        if self._host.web_search is not None:
            self._host.web_search.use(searcher)
        return label

    def _parse(self, line: str) -> Request | None:
        if len(line) > MAX_LINE_BYTES:
            log.warning("control.too_long")
            return None
        try:
            return Request.model_validate(json.loads(line))
        except (json.JSONDecodeError, ValidationError):
            log.warning("control.invalid")
            return None


async def read_lines(
    source: asyncio.StreamReader, handle: Callable[[str], Coroutine[Any, Any, None]]
) -> None:
    pending: set[asyncio.Task[None]] = set()
    while True:
        try:
            raw = await source.readline()
        except ValueError:
            log.warning("control.too_long")
            continue
        if not raw:
            break
        task: asyncio.Task[None] = asyncio.create_task(handle(raw.decode(errors="replace").strip()))
        pending.add(task)
        task.add_done_callback(pending.discard)
    for task in pending:
        task.cancel()
