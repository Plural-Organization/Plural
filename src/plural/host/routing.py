"""Picks the cheaper model the host can reach alongside the main one.

The `fast` role takes work that does not need the main model, like summarizing the conversation
and, later, read-only sub-agents. It comes from the credentials the host already has: a cheaper
model of the same provider, or one reachable with a key in the environment.
"""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

from plural.agent.providers.base import LLMProvider
from plural.host.config import HostSettings
from plural.host.providers import ConfigError, build_provider, provider_secrets, resolve_api_key

ANTHROPIC_FAST: Final = "claude-haiku-5-5"
OPENAI_FAST: Final = "gpt-5-mini"
OPENAI_COMPATIBLE_FAST: Final[Mapping[str, str]] = {
    "generativelanguage.googleapis.com": "gemini-2.5-flash",
}
CHEAP_HINTS: Final = ("haiku", "mini", "flash", "nano", "lite", "small")


@dataclass(frozen=True, slots=True)
class Helper:
    provider: LLMProvider
    label: str
    secrets: tuple[str, ...] = ()


def fast_settings(settings: HostSettings, environ: Mapping[str, str]) -> HostSettings | None:
    """The settings for the fast role, or None when nothing cheaper is reachable."""
    if settings.fast_model:
        provider = settings.fast_provider or settings.resolved_provider(environ)
        return settings.model_copy(update={"provider": provider, "model": settings.fast_model})
    provider = settings.resolved_provider(environ)
    if _cheap(settings.model):
        return None
    match provider:
        case "anthropic" | "anthropic_oauth":
            return settings.model_copy(update={"model": ANTHROPIC_FAST})
        case "openai":
            model = _openai_fast(settings.base_url)
            return settings.model_copy(update={"model": model}) if model else None
        case "claude_code" | "codex_cli":
            if environ.get("ANTHROPIC_API_KEY"):
                return settings.model_copy(
                    update={
                        "provider": "anthropic",
                        "model": ANTHROPIC_FAST,
                        "api_key": None,
                        "base_url": None,
                    }
                )
            if environ.get("OPENAI_API_KEY"):
                return settings.model_copy(
                    update={
                        "provider": "openai",
                        "model": OPENAI_FAST,
                        "api_key": None,
                        "base_url": None,
                    }
                )
            return None
        case "fake":
            return None


def build_helper(settings: HostSettings, environ: Mapping[str, str] | None = None) -> Helper | None:
    variables = os.environ if environ is None else environ
    fast = fast_settings(settings, variables)
    if fast is None:
        return None
    key = resolve_api_key(fast, variables)
    try:
        provider = build_provider(fast, key)
    except ConfigError:
        return None
    return Helper(provider=provider, label=fast.model or "", secrets=provider_secrets(fast, key))


def _openai_fast(base_url: str | None) -> str | None:
    if base_url is None:
        return OPENAI_FAST
    host = urlsplit(base_url).hostname or ""
    return OPENAI_COMPATIBLE_FAST.get(host)


def _cheap(model: str | None) -> bool:
    if model is None:
        return False
    parts = set(re.split(r"[^a-z0-9]+", model.lower()))
    return any(hint in parts for hint in CHEAP_HINTS)
