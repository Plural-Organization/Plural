"""Builds the LLM provider the host settings ask for."""

from collections.abc import Mapping

from plural.agent.providers import anthropic_api
from plural.agent.providers.anthropic_api import AnthropicProvider
from plural.agent.providers.anthropic_oauth import AnthropicOAuthProvider, load_credentials
from plural.agent.providers.base import LLMProvider
from plural.agent.providers.claude_code import ClaudeCodeProvider
from plural.agent.providers.codex_cli import CodexCliProvider
from plural.agent.providers.fake import DemoProvider
from plural.agent.providers.openai_compat import OpenAIProvider
from plural.host.config import HostSettings

KEY_VARIABLES = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
LOCAL_SERVER_KEY = "not-needed"


class ConfigError(Exception):
    pass


def resolve_api_key(settings: HostSettings, environ: Mapping[str, str]) -> str | None:
    if settings.api_key is not None:
        return settings.api_key.get_secret_value()
    variable = KEY_VARIABLES.get(settings.resolved_provider(environ))
    return environ.get(variable) if variable else None


def provider_secrets(settings: HostSettings, api_key: str | None) -> tuple[str, ...]:
    if settings.resolved_provider() == "anthropic_oauth":
        credentials = load_credentials(settings.state_dir / "anthropic-oauth.json")
        return (credentials.access, credentials.refresh)
    return (api_key,) if api_key else ()


def build_provider(settings: HostSettings, api_key: str | None) -> LLMProvider:
    match settings.resolved_provider():
        case "fake":
            return DemoProvider()
        case "anthropic":
            if not api_key:
                raise ConfigError(
                    "set PLURAL_API_KEY or ANTHROPIC_API_KEY for the anthropic provider"
                )
            return AnthropicProvider(
                api_key=api_key,
                model=settings.model or anthropic_api.DEFAULT_MODEL,
                max_tokens=settings.max_output_tokens or anthropic_api.DEFAULT_MAX_TOKENS,
                effort=settings.effort,
                base_url=settings.base_url,
            )
        case "anthropic_oauth":
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
            return OpenAIProvider(
                api_key=api_key or LOCAL_SERVER_KEY,
                model=settings.model,
                base_url=settings.base_url,
                max_tokens=settings.max_output_tokens,
                effort=settings.effort,
            )
