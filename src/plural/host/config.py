import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from plural.agent.providers.base import Effort
from plural.protocol.models import PromptMode


class HostSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PLURAL_", extra="ignore")

    workspace: Path = Field(default_factory=Path.cwd)
    data_dir: Path = Path("~/.plural")
    room: str | None = None
    host_name: str = "host"
    prompt_mode: PromptMode | None = None
    bind_host: str = "127.0.0.1"
    port: int = 7777
    public_url: str | None = None
    relay_url: str | None = None
    provider: (
        Literal["fake", "anthropic", "anthropic_oauth", "claude_code", "codex_cli", "openai"] | None
    ) = None
    model: str | None = None
    api_key: SecretStr | None = None
    base_url: str | None = None
    effort: Effort | None = None
    max_output_tokens: int | None = Field(default=None, gt=0)
    first_token_timeout_s: float = Field(default=120, gt=0)
    idle_timeout_s: float = Field(default=60, gt=0)
    rejection_limit: int = Field(default=2, gt=0)
    context_window: int = Field(default=128_000, gt=0)
    compact_at: float = Field(default=0.75, gt=0, lt=1)
    approval_timeout_s: float = Field(default=120, gt=0)
    token_ttl_s: int = Field(default=86_400, gt=0, le=86_400)
    invite_ttl_s: int = Field(default=3600, gt=0, le=86_400)
    max_attachment_bytes: int = Field(default=1_048_576, gt=0)
    # base64 grows an upload by a third, and a WebSocket frame holds at most 4 MB
    max_image_bytes: int = Field(default=2_500_000, gt=0, le=2_900_000)
    typing_ttl_s: float = Field(default=6, gt=0)
    browser: str = "launch"
    web_search: bool = True
    web_search_model: str | None = None
    web_search_context_size: Literal["low", "medium", "high"] = "medium"
    web_search_max_uses: int | None = Field(default=5, gt=0)
    web_search_allowed_domains: list[str] = Field(default_factory=list[str])
    web_search_blocked_domains: list[str] = Field(default_factory=list[str])
    web_search_city: str | None = None
    web_search_region: str | None = None
    web_search_country: str | None = None
    web_search_timezone: str | None = None

    def resolved_provider(
        self, environ: Mapping[str, str] | None = None
    ) -> Literal["fake", "anthropic", "anthropic_oauth", "claude_code", "codex_cli", "openai"]:
        if self.provider is not None:
            return self.provider
        variables = os.environ if environ is None else environ
        if variables.get("ANTHROPIC_API_KEY"):
            return "anthropic"
        if variables.get("OPENAI_API_KEY") or (self.base_url and self.model):
            return "openai"
        return "fake"

    def agent_label(self, environ: Mapping[str, str] | None = None) -> str:
        provider = self.resolved_provider(environ)
        if provider == "fake":
            return "demo agent (scripted)"
        if provider == "anthropic_oauth":
            return f"Claude OAuth · {self.model or 'claude-haiku-4-5'}"
        if provider == "claude_code":
            return f"Claude Code · {self.model or 'claude-sonnet-5-5'}"
        if provider == "codex_cli":
            return f"Codex CLI · {self.model or 'gpt-6.1-sol'}"
        model = self.model or ("claude-opus-5-5" if provider == "anthropic" else "")
        where = " · local" if provider == "openai" and self.base_url else ""
        return f"{provider} · {model}{where}" if model else provider

    @property
    def state_dir(self) -> Path:
        return self.data_dir.expanduser()

    def room_url(self, room: str) -> str:
        base = self.public_url or self.relay_url or f"ws://{self.bind_host}:{self.port}"
        return f"{base.rstrip('/')}/{room}"
