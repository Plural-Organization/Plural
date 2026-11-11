import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from plural.agent.providers.base import Effort
from plural.agent.providers.catalog import Preset, preset
from plural.agent.providers.preset import AGENT_CLI_ADAPTERS, Adapter
from plural.protocol.models import AdmissionMode, PromptMode

# The relay a host and a team use when none is named. Everything else is opt-in: --local stays on
# this machine, --bind and --public-url serve directly, --relay picks another relay.
DEFAULT_RELAY_URL = "wss://relay.plrl.host"
# Where a computer is linked to an account.
DEFAULT_ACCOUNTS_URL = "https://accounts.plrl.host"


class HostSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PLURAL_", extra="ignore")

    workspace: Path = Field(default_factory=Path.cwd)
    data_dir: Path = Path("~/.plural")
    room: str | None = None
    import_from: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=80)
    host_name: str = "host"
    prompt_mode: PromptMode | None = None
    admission: AdmissionMode | None = None
    bind_host: str = "127.0.0.1"
    port: int = 7777
    public_url: str | None = None
    relay_url: str | None = None
    # The MCP gateway a chat service sends chats through. Off until one is named.
    mcp_url: str | None = None
    team: bool = False
    # Which of this computer's teams a team session shows to; None is the one in team.json.
    team_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    team_roster_ttl_s: float = Field(default=30, gt=0)
    preset: str | None = None
    provider: Adapter | None = None
    model: str | None = None
    fast_provider: Adapter | None = None
    fast_model: str | None = None
    api_key: SecretStr | None = None
    base_url: str | None = None
    effort: Effort | None = None
    max_output_tokens: int | None = Field(default=None, gt=0)
    first_token_timeout_s: float = Field(default=120, gt=0)
    idle_timeout_s: float = Field(default=60, gt=0)
    rejection_limit: int = Field(default=2, gt=0)
    guest_run_tokens: int | None = Field(default=None, gt=0)
    pinned_tools: str = ""
    # None: the provider says how much its model takes; set it for a model that cannot.
    context_window: int | None = Field(default=None, gt=0)
    compact_reserve: int = Field(default=16_384, ge=0)
    compact_keep: int = Field(default=20_000, ge=0)
    dump_requests: bool = False
    approval_timeout_s: float = Field(default=120, gt=0)
    token_ttl_s: int = Field(default=86_400, gt=0, le=86_400)
    invite_ttl_s: int = Field(default=3600, gt=0, le=86_400)
    max_attachment_bytes: int = Field(default=1_048_576, gt=0)
    # base64 grows an upload by a third, and a WebSocket frame holds at most 4 MB
    max_image_bytes: int = Field(default=2_500_000, gt=0, le=2_900_000)
    typing_ttl_s: float = Field(default=6, gt=0)
    join_timeout_s: float = Field(default=120, gt=0)
    max_pending_joins: int = Field(default=5, gt=0)
    max_participants: int = Field(default=20, gt=1)
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

    @model_validator(mode="after")
    def _use_preset(self) -> Self:
        for name, value in preset_values(
            self.preset, model=self.model, base_url=self.base_url
        ).items():
            if getattr(self, name) is None:
                setattr(self, name, value)
        return self

    @property
    def catalog_entry(self) -> Preset | None:
        return preset(self.preset) if self.preset else None

    def resolved_provider(self, environ: Mapping[str, str] | None = None) -> Adapter:
        if self.provider is not None:
            return self.provider
        variables = os.environ if environ is None else environ
        if variables.get("ANTHROPIC_API_KEY"):
            return "anthropic"
        if variables.get("OPENAI_API_KEY") or (self.base_url and self.model):
            return "openai"
        return "fake"

    def agent_label(self, environ: Mapping[str, str] | None = None) -> str:
        entry = self.catalog_entry
        if entry is not None and entry.adapter != "fake":
            return f"{entry.label} · {self.model or 'default'}"
        provider = self.resolved_provider(environ)
        if provider == "fake":
            return "demo agent (scripted)"
        if provider == "anthropic_oauth":
            return f"Claude OAuth · {self.model or 'claude-haiku-4-5'}"
        if provider == "claude_code":
            return f"Claude Code · {self.model or 'claude-sonnet-5-5'}"
        if provider == "codex_cli":
            return f"Codex CLI · {self.model or 'gpt-6.1-sol'}"
        if provider in AGENT_CLI_ADAPTERS:
            return f"{provider} · {self.model or 'default'}"
        model = self.model or ("claude-opus-5-5" if provider == "anthropic" else "")
        where = " · local" if provider == "openai" and self.base_url else ""
        return f"{provider} · {model}{where}" if model else provider

    @property
    def state_dir(self) -> Path:
        return self.data_dir.expanduser()

    def room_url(self, room: str) -> str:
        base = self.public_url or self.relay_url or f"ws://{self.bind_host}:{self.port}"
        return f"{base.rstrip('/')}/{room}"


def preset_values(
    preset_id: str | None, *, model: str | None, base_url: str | None
) -> dict[str, str]:
    """The provider, endpoint and default model a catalog preset stands for."""
    if preset_id is None:
        return {}
    entry = preset(preset_id)
    if entry is None:
        raise ValueError(f"unknown preset {preset_id!r}")
    values = {"provider": entry.adapter}
    endpoint = (base_url if entry.editable_url else None) or entry.base_url
    if endpoint:
        values["base_url"] = endpoint
    if model or entry.models:
        values["model"] = model or entry.models[0]
    return values
