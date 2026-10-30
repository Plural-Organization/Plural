"""Builds the LLM provider the host settings ask for."""

from collections.abc import Mapping
from typing import NoReturn

from plural.agent.providers.base import LLMProvider
from plural.agent.providers.cli.claude_code import ClaudeCodeProvider
from plural.agent.providers.cli.codex_cli import CodexCliProvider
from plural.agent.providers.fake import DemoProvider
from plural.host.config import HostSettings
from plural.host.extras import MODULES, Extra, hint

KEY_VARIABLES = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
LOCAL_SERVER_KEY = "not-needed"


class ConfigError(Exception):
    pass


def extra_missing(extra: Extra, error: ModuleNotFoundError) -> NoReturn:
    """Turn a missing SDK into an install hint; any other missing module is a real bug."""
    if (error.name or "").partition(".")[0] not in MODULES[extra]:
        raise error
    raise ConfigError(
        f"the {extra} provider is not installed: choose Install in the plural window, "
        f"or run: {hint(extra)}"
    ) from error


def resolve_api_key(settings: HostSettings, environ: Mapping[str, str]) -> str | None:
    if settings.api_key is not None:
        return settings.api_key.get_secret_value()
    entry = settings.catalog_entry
    if entry is not None:
        # A preset's key lives in its own variables: never send OPENAI_API_KEY to another vendor.
        return next((environ[name] for name in entry.key_env if environ.get(name)), None)
    variable = KEY_VARIABLES.get(settings.resolved_provider(environ))
    return environ.get(variable) if variable else None


def provider_secrets(settings: HostSettings, api_key: str | None) -> tuple[str, ...]:
    if settings.resolved_provider() == "anthropic_oauth":
        try:
            from plural.agent.providers.api.anthropic.oauth import load_credentials
        except ModuleNotFoundError as error:
            extra_missing("anthropic", error)
        credentials = load_credentials(settings.state_dir / "anthropic-oauth.json")
        return (credentials.access, credentials.refresh)
    return (api_key,) if api_key else ()


def build_provider(settings: HostSettings, api_key: str | None) -> LLMProvider:
    entry = settings.catalog_entry
    if entry is not None and entry.needs_key and not api_key:
        where = " or ".join((*entry.key_env, "PLURAL_API_KEY"))
        raise ConfigError(
            f"{entry.label} needs an API key: set {where}, or enter it in the settings"
        )
    match settings.resolved_provider():
        case "fake":
            return DemoProvider()
        case "anthropic":
            if not api_key:
                raise ConfigError(
                    "set PLURAL_API_KEY or ANTHROPIC_API_KEY for the anthropic provider"
                )
            try:
                from plural.agent.providers.api.anthropic import adapter as anthropic_api
                from plural.agent.providers.api.anthropic.adapter import AnthropicProvider
            except ModuleNotFoundError as error:
                extra_missing("anthropic", error)
            return AnthropicProvider(
                api_key=api_key,
                model=settings.model or anthropic_api.DEFAULT_MODEL,
                max_tokens=settings.max_output_tokens or anthropic_api.DEFAULT_MAX_TOKENS,
                effort=settings.effort,
                base_url=settings.base_url,
            )
        case "anthropic_oauth":
            try:
                from plural.agent.providers.api.anthropic import adapter as anthropic_api
                from plural.agent.providers.api.anthropic.oauth import AnthropicOAuthProvider
            except ModuleNotFoundError as error:
                extra_missing("anthropic", error)
            return AnthropicOAuthProvider(
                credentials_path=settings.state_dir / "anthropic-oauth.json",
                model=settings.model or anthropic_api.DEFAULT_OAUTH_MODEL,
                max_tokens=settings.max_output_tokens or anthropic_api.DEFAULT_MAX_TOKENS,
                effort=settings.effort,
            )
        case "claude_code":
            return ClaudeCodeProvider(
                workspace=settings.workspace,
                model=settings.model or "claude-sonnet-5-5",
            )
        case "codex_cli":
            return CodexCliProvider(
                workspace=settings.workspace,
                model=settings.model or CodexCliProvider.DEFAULT_MODEL,
            )
        case "openai":
            if not settings.model:
                raise ConfigError("set PLURAL_MODEL for the openai provider")
            if not api_key and settings.base_url is None:
                raise ConfigError("set PLURAL_API_KEY or OPENAI_API_KEY for the openai provider")
            try:
                from plural.agent.providers.api.openai_compat.adapter import OpenAIProvider
            except ModuleNotFoundError as error:
                extra_missing("openai", error)
            return OpenAIProvider(
                api_key=api_key or LOCAL_SERVER_KEY,
                model=settings.model,
                base_url=settings.base_url,
                max_tokens=settings.max_output_tokens,
                effort=settings.effort,
            )
