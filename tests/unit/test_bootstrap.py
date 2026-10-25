import pytest
from pydantic import SecretStr

from plural.agent.providers.anthropic_api import AnthropicProvider
from plural.agent.providers.fake import DemoProvider
from plural.agent.providers.openai_compat import OpenAIProvider
from plural.host.bootstrap import ConfigError, build_provider, resolve_api_key
from plural.host.config import HostSettings


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
