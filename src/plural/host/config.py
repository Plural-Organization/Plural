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
    provider: Literal["fake", "anthropic", "openai"] | None = None
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
    typing_ttl_s: float = Field(default=6, gt=0)

    def resolved_provider(
        self, environ: Mapping[str, str] | None = None
    ) -> Literal["fake", "anthropic", "openai"]:
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
        model = self.model or ("claude-opus-5-5" if provider == "anthropic" else "")
        where = " · local" if provider == "openai" and self.base_url else ""
        return f"{provider} · {model}{where}" if model else provider

    @property
    def state_dir(self) -> Path:
        return self.data_dir.expanduser()

    def room_url(self, room: str) -> str:
        base = self.public_url or self.relay_url or f"ws://{self.bind_host}:{self.port}"
        return f"{base.rstrip('/')}/{room}"
