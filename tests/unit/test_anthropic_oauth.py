import asyncio
import json
import time
from pathlib import Path

import pytest

from plural.agent.providers import anthropic_oauth
from plural.agent.providers.anthropic_oauth import (
    AnthropicOAuthProvider,
    OAuthCredentials,
    load_credentials,
    save_credentials,
)
from plural.agent.providers.base import ProviderError
from plural.host.bootstrap import build_provider, provider_secrets
from plural.host.config import HostSettings
from plural.host.control import AgentConfig, provider_for
from plural.security.secrets import Redactor


def test_oauth_provider_requires_a_saved_login(tmp_path: Path) -> None:
    settings = HostSettings(provider="anthropic_oauth", data_dir=tmp_path)
    with pytest.raises(ProviderError, match="sign in again"):
        build_provider(settings, None)

    credentials = OAuthCredentials(
        access="access-123", refresh="refresh-123", expires=time.time() + 3600
    )
    path = tmp_path / "anthropic-oauth.json"
    save_credentials(path, credentials)
    assert path.stat().st_mode & 0o777 == 0o600
    assert isinstance(build_provider(settings, None), AnthropicOAuthProvider)
    selected, configured, key = provider_for(settings, AgentConfig(provider="anthropic_oauth"))
    assert isinstance(selected, AnthropicOAuthProvider)
    assert configured.provider == "anthropic_oauth"
    assert key is None
    assert settings.agent_label({}) == "Claude OAuth · claude-haiku-4-5"
    assert load_credentials(path) == credentials
    redactor = Redactor(provider_secrets(settings, None))
    assert "access-123" not in redactor.redact("access-123 refresh-123")
    assert "refresh-123" not in redactor.redact("access-123 refresh-123")


async def test_expired_oauth_token_is_refreshed_and_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "anthropic-oauth.json"
    save_credentials(path, OAuthCredentials(access="old", refresh="refresh-old", expires=1))
    calls: list[str] = []

    def refresh(value: str) -> OAuthCredentials:
        calls.append(value)
        return OAuthCredentials(access="new", refresh="refresh-new", expires=time.time() + 3600)

    monkeypatch.setattr(anthropic_oauth, "_refresh", refresh)
    provider = AnthropicOAuthProvider(
        credentials_path=path, model="claude-sonnet-5-5", max_tokens=100, effort=None
    )
    first = provider._token()  # pyright: ignore[reportPrivateUsage]
    second = provider._token()  # pyright: ignore[reportPrivateUsage]
    assert await asyncio.gather(first, second) == ["new", "new"]
    assert calls == ["refresh-old"]
    assert json.loads(path.read_text())["refresh"] == "refresh-new"
