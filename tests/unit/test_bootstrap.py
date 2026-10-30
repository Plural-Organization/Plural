import pytest
from pydantic import SecretStr

from plural.agent.providers.api.anthropic.adapter import AnthropicProvider
from plural.agent.providers.api.openai_compat.adapter import OpenAIProvider
from plural.agent.providers.fake import DemoProvider
from plural.host.config import HostSettings
from plural.host.providers import ConfigError, build_provider, resolve_api_key


def test_explicit_key_wins_over_environment() -> None:
    settings = HostSettings(provider="anthropic", api_key=SecretStr("explicit"))
    assert resolve_api_key(settings, {"ANTHROPIC_API_KEY": "env"}) == "explicit"


def test_vendor_variable_is_used_for_its_provider_only() -> None:
    environ = {"ANTHROPIC_API_KEY": "a", "OPENAI_API_KEY": "o"}
    assert resolve_api_key(HostSettings(provider="anthropic"), environ) == "a"
    assert resolve_api_key(HostSettings(provider="openai"), environ) == "o"
    assert resolve_api_key(HostSettings(provider="fake"), environ) is None


def test_fake_provider_needs_no_key() -> None:
    assert isinstance(build_provider(HostSettings(provider="fake"), None), DemoProvider)


def test_anthropic_requires_key() -> None:
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        build_provider(HostSettings(provider="anthropic"), None)
    assert isinstance(build_provider(HostSettings(provider="anthropic"), "k"), AnthropicProvider)


def test_openai_requires_model_and_key_unless_local() -> None:
    with pytest.raises(ConfigError, match="PLURAL_MODEL"):
        build_provider(HostSettings(provider="openai"), "k")
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        build_provider(HostSettings(provider="openai", model="gpt"), None)
    local = HostSettings(provider="openai", model="qwen", base_url="http://localhost:11434/v1")
    assert isinstance(build_provider(local, None), OpenAIProvider)


def test_the_provider_follows_the_keys_in_the_environment() -> None:
    assert HostSettings().resolved_provider({}) == "fake"
    assert HostSettings().resolved_provider({"ANTHROPIC_API_KEY": "a"}) == "anthropic"
    assert HostSettings().resolved_provider({"OPENAI_API_KEY": "o"}) == "openai"
    both = {"ANTHROPIC_API_KEY": "a", "OPENAI_API_KEY": "o"}
    assert HostSettings().resolved_provider(both) == "anthropic"
    local = HostSettings(base_url="http://localhost:11434/v1", model="qwen3:4b")
    assert local.resolved_provider({}) == "openai"
    assert HostSettings(provider="fake").resolved_provider(both) == "fake"


def test_the_agent_label_says_what_answers() -> None:
    assert HostSettings(provider="fake").agent_label({}) == "demo agent (scripted)"
    assert HostSettings(provider="anthropic").agent_label({}) == "anthropic · claude-opus-5-5"
    assert HostSettings(provider="openai", model="gpt-5").agent_label({}) == "openai · gpt-5"
    local = HostSettings(provider="openai", model="qwen3:4b", base_url="http://localhost:11434/v1")
    assert local.agent_label({}) == "openai · qwen3:4b · local"
