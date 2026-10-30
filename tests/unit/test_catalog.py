import json
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from plural.agent.providers.api.openai_compat import OpenAIProvider
from plural.agent.providers.catalog import PRESETS, preset
from plural.host.config import HostSettings
from plural.host.control import AgentConfig, settings_for
from plural.host.providers import ConfigError, build_provider, resolve_api_key

CATALOG = Path(__file__).resolve().parents[2] / "tui" / "src" / "catalog.json"


def test_the_catalog_is_consistent_and_the_client_copy_is_current() -> None:
    ids = [entry.id for entry in PRESETS]
    assert len(ids) == len(set(ids))
    for entry in PRESETS:
        assert (
            entry.base_url
            or entry.editable_url
            or entry.adapter != "openai"
            or entry.id == "openai"
        )
        assert not (entry.connection == "local" and entry.needs_key)
    assert json.loads(CATALOG.read_text()) == [entry.to_json() for entry in PRESETS]


def test_a_preset_fills_the_provider_endpoint_and_model(tmp_path: Path) -> None:
    settings = HostSettings(preset="nvidia", workspace=tmp_path)
    nvidia = preset("nvidia")
    assert nvidia is not None
    assert settings.resolved_provider({}) == "openai"
    assert settings.base_url == "https://integrate.api.nvidia.com/v1"
    assert settings.model == nvidia.models[0]
    assert settings.agent_label({}) == f"NVIDIA NIM · {nvidia.models[0]}"

    chosen = HostSettings(preset="nvidia", model="meta/llama-3.1-70b-instruct", workspace=tmp_path)
    assert chosen.model == "meta/llama-3.1-70b-instruct"


def test_a_preset_key_comes_only_from_its_own_variable(tmp_path: Path) -> None:
    settings = HostSettings(preset="nvidia", workspace=tmp_path)
    environ = {"OPENAI_API_KEY": "sk-openai", "NVIDIA_API_KEY": "nvapi-1"}
    assert resolve_api_key(settings, environ) == "nvapi-1"
    assert resolve_api_key(settings, {"OPENAI_API_KEY": "sk-openai"}) is None
    provider = build_provider(settings, "nvapi-1")
    assert isinstance(provider, OpenAIProvider)

    explicit = HostSettings(preset="nvidia", api_key=SecretStr("given"), workspace=tmp_path)
    assert resolve_api_key(explicit, environ) == "given"


def test_an_unknown_preset_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="unknown preset 'nope'"):
        HostSettings(preset="nope", workspace=tmp_path)
    with pytest.raises(ConfigError, match="unknown preset"):
        settings_for(HostSettings(workspace=tmp_path), AgentConfig(preset="nope"))


def test_the_client_sends_a_preset_and_the_host_expands_it(tmp_path: Path) -> None:
    base = HostSettings(workspace=tmp_path)
    nvidia = settings_for(base, AgentConfig(preset="nvidia", api_key=SecretStr("nvapi-1")))
    assert (nvidia.provider, nvidia.base_url) == ("openai", "https://integrate.api.nvidia.com/v1")
    assert nvidia.model == "meta/llama-3.3-70b-instruct"

    azure = settings_for(
        base, AgentConfig(preset="azure", model="dep", base_url="https://r.openai.azure.com/v1")
    )
    assert (azure.base_url, azure.model) == ("https://r.openai.azure.com/v1", "dep")

    legacy = settings_for(base, AgentConfig(provider="fake"))
    assert legacy.resolved_provider({}) == "fake"
    with pytest.raises(ConfigError, match="choose a provider"):
        settings_for(base, AgentConfig())
