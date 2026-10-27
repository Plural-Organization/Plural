import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pydantic import SecretStr

from plural.agent.providers.base import LlmEvent, LlmRequest, ProviderError, TextDelta
from plural.agent.providers.fake import FakeProvider, reply
from plural.host import control
from plural.host.bootstrap import ConfigError
from plural.host.config import HostSettings
from plural.host.control import AgentConfig, probe, provider_for, settings_for
from plural.security.secrets import Redactor

BASE = HostSettings(provider="fake", context_window=50_000)


def test_a_config_overrides_the_base_settings_and_keeps_the_rest() -> None:
    config = AgentConfig(
        provider="openai",
        model="gemini-2.5-flash",
        base_url="https://example.test/v1",
        api_key=SecretStr("k" * 20),
        context_window=8192,
    )
    settings = settings_for(BASE, config)
    assert (settings.provider, settings.model, settings.base_url) == (
        "openai",
        "gemini-2.5-flash",
        "https://example.test/v1",
    )
    assert settings.context_window == 8192
    assert settings_for(BASE, AgentConfig(provider="fake")).context_window == 50_000


def test_an_empty_model_or_url_means_the_default() -> None:
    settings = settings_for(BASE, AgentConfig(provider="openai", model="", base_url=""))
    assert settings.model is None
    assert settings.base_url is None


def test_providers_are_built_from_a_config_and_missing_pieces_are_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def claude_path(command: str) -> str:
        assert command == "claude"
        return "/usr/bin/claude"

    monkeypatch.setattr("plural.agent.providers.claude_code.shutil.which", claude_path)
    provider, settings, key = provider_for(BASE, AgentConfig(provider="fake"))
    assert provider is not None
    assert key is None
    assert settings.agent_label({}) == "demo agent (scripted)"

    local = AgentConfig(provider="openai", model="qwen3:4b", base_url="http://127.0.0.1:11434/v1")
    _, local_settings, local_key = provider_for(BASE, local)
    assert local_key is None
    assert local_settings.agent_label({}) == "openai · qwen3:4b · local"

    _, cli_settings, cli_key = provider_for(BASE, AgentConfig(provider="claude_code"))
    assert cli_key is None
    assert cli_settings.agent_label({}) == "Claude Code · claude-sonnet-5-5"

    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        provider_for(HostSettings(), AgentConfig(provider="anthropic"))
    with pytest.raises(ConfigError, match="PLURAL_MODEL"):
        provider_for(BASE, AgentConfig(provider="openai"))


def test_the_key_comes_from_the_config_and_never_from_the_host_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-the-environment-0123456789")
    _, _, key = provider_for(
        HostSettings(), AgentConfig(provider="anthropic", api_key=SecretStr("typed-key-0123456789"))
    )
    assert key == "typed-key-0123456789"


async def test_a_working_provider_is_reported_with_its_latency() -> None:
    message = await probe(FakeProvider([reply("ok")]))
    assert message.startswith("answered in ")


async def test_probe_sends_a_nonempty_system_message() -> None:
    class RecordingProvider:
        system = ""

        async def stream(
            self, request: LlmRequest, *, cancel: asyncio.Event
        ) -> AsyncIterator[LlmEvent]:
            self.system = request.system
            yield TextDelta(text="ok")

    provider = RecordingProvider()
    await probe(provider)
    assert provider.system


class Failing:
    def stream(self, request: LlmRequest, *, cancel: asyncio.Event) -> AsyncIterator[LlmEvent]:
        async def run() -> AsyncIterator[LlmEvent]:
            raise ProviderError("401 invalid api key")
            yield TextDelta(text="")

        return run()


class Silent:
    def stream(self, request: LlmRequest, *, cancel: asyncio.Event) -> AsyncIterator[LlmEvent]:
        async def run() -> AsyncIterator[LlmEvent]:
            await asyncio.Event().wait()
            yield TextDelta(text="")

        return run()


async def test_a_provider_that_fails_or_stays_silent_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ProviderError, match="invalid api key"):
        await probe(Failing())
    monkeypatch.setattr(control, "PROBE_TIMEOUT_S", 0.1)
    with pytest.raises(ProviderError, match="no answer"):
        await probe(Silent())


def test_a_secret_added_later_is_masked_like_the_first_ones() -> None:
    redactor = Redactor(["first-secret-0123456789"])
    redactor.add("second-secret-9876543210")
    redactor.add("short")
    redactor.add("second-secret-9876543210")
    masked = redactor.redact("a first-secret-0123456789 b second-secret-9876543210 c short")
    assert "first-secret" not in masked
    assert "second-secret" not in masked
    assert "short" in masked


async def test_the_data_directory_is_not_touched(tmp_path: Path) -> None:
    assert not (tmp_path / "data").exists()
