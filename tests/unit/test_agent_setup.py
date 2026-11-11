import json
import os
import stat
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from typer.testing import CliRunner

from plural.agent.providers.catalog import preset
from plural.agent.providers.preset import Preset
from plural.agent_setup import (
    AgentSetup,
    AgentSetupError,
    AgentStore,
    Choice,
    State,
    probes,
    service,
)
from plural.agent_setup.service import config_for, readiness_of
from plural.cli.main import app
from plural.host import tools

SECRET = "sk-ant-api03-0123456789abcdefghijklmnop"
runner = CliRunner()


def known(provider_id: str) -> Preset:
    entry = preset(provider_id)
    assert entry is not None
    return entry


def ready(
    entry: Preset,
    tmp_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
    signed_in: Mapping[str, bool | None] | None = None,
    servers: frozenset[str] = frozenset(),
) -> service.Readiness:
    return readiness_of(
        entry, AgentStore(tmp_path), tmp_path, environ or {}, signed_in or {}, servers
    )


def installed(answer: bool) -> Callable[[str], bool]:
    def check(_: str) -> bool:
        return answer

    return check


def on_path(found: str | None) -> Callable[[str], str | None]:
    def which(_: str) -> str | None:
        return found

    return which


@pytest.fixture(autouse=True)
def quiet_computer(monkeypatch: pytest.MonkeyPatch) -> None:
    """No real CLI, no real model server: the tests say what this computer has."""

    async def none() -> None:
        return None

    async def no_servers() -> list[probes.LocalServer]:
        return []

    monkeypatch.setattr(probes, "claude_signed_in", none)
    monkeypatch.setattr(probes, "codex_signed_in", none)
    monkeypatch.setattr(probes, "local_servers", no_servers)


# --- the store -------------------------------------------------------------------------------


def test_a_key_is_saved_privately_and_read_back(tmp_path: Path) -> None:
    store = AgentStore(tmp_path)
    store.set_key("anthropic", f"  {SECRET}\n")
    assert store.key("anthropic") == SECRET
    mode = stat.S_IMODE(os.stat(tmp_path / "credentials.json").st_mode)
    assert mode == 0o600


def test_a_key_keeps_the_file_format_the_terminal_client_wrote(tmp_path: Path) -> None:
    (tmp_path / "credentials.json").write_text(
        json.dumps({"keys": {"openai": "old-key"}, "other": 1}), encoding="utf-8"
    )
    store = AgentStore(tmp_path)
    assert store.key("openai") == "old-key"
    store.set_key("anthropic", SECRET)
    saved = json.loads((tmp_path / "credentials.json").read_text(encoding="utf-8"))
    assert saved == {"keys": {"openai": "old-key", "anthropic": SECRET}, "other": 1}


@pytest.mark.parametrize("bad", ["", "   ", "two words", "a" * 5000])
def test_something_that_is_not_a_key_is_refused(tmp_path: Path, bad: str) -> None:
    with pytest.raises(AgentSetupError):
        AgentStore(tmp_path).set_key("anthropic", bad)


def test_a_provider_id_that_is_not_one_is_refused(tmp_path: Path) -> None:
    with pytest.raises(AgentSetupError):
        AgentStore(tmp_path).set_key("../x", SECRET)


def test_a_key_can_be_forgotten(tmp_path: Path) -> None:
    store = AgentStore(tmp_path)
    store.set_key("anthropic", SECRET)
    store.clear_key("anthropic")
    assert store.key("anthropic") is None


def test_a_choice_is_remembered_and_the_terminal_clients_other_settings_survive(
    tmp_path: Path,
) -> None:
    (tmp_path / "tui.json").write_text(json.dumps({"theme": "tokyo", "bell": False}), "utf-8")
    store = AgentStore(tmp_path)
    assert store.current().preset == "demo"
    store.choose(Choice(preset="ollama", model="qwen3:4b", base_url="http://127.0.0.1:11434/v1"))
    saved = json.loads((tmp_path / "tui.json").read_text(encoding="utf-8"))
    assert saved["theme"] == "tokyo"
    assert saved["bell"] is False
    assert saved["agent"]["preset"] == "ollama"
    assert saved["agentChoices"]["ollama"]["model"] == "qwen3:4b"
    assert "fastModel" not in saved["agent"]
    assert store.current().model == "qwen3:4b"
    assert store.saved("ollama") == store.current()
    assert store.saved("openai") is None


def test_a_damaged_file_means_the_default(tmp_path: Path) -> None:
    (tmp_path / "tui.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "credentials.json").write_text("[]", encoding="utf-8")
    store = AgentStore(tmp_path)
    assert store.current().preset == "demo"
    assert store.keys() == {}


# --- what a provider needs -------------------------------------------------------------------


def test_a_provider_with_a_key_needs_one_until_it_has_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service.extras, "is_installed", installed(True))
    entry = known("anthropic")
    assert ready(entry, tmp_path).state is State.NEEDS_KEY
    assert ready(entry, tmp_path, environ={"ANTHROPIC_API_KEY": SECRET}).state is State.READY
    AgentStore(tmp_path).set_key("anthropic", SECRET)
    assert ready(entry, tmp_path).state is State.READY


def test_a_missing_sdk_comes_before_a_missing_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service.extras, "is_installed", installed(False))
    found = ready(known("anthropic"), tmp_path)
    assert found.state is State.NEEDS_SDK
    assert found.command is not None
    assert "plural-agent[anthropic]" in found.command


def test_claude_code_needs_the_cli_then_a_sign_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry = known("claude_code")
    monkeypatch.setattr(tools, "is_installed", installed(False))
    missing = ready(entry, tmp_path)
    assert missing.state is State.NEEDS_INSTALL
    assert missing.command == "npm install -g @anthropic-ai/claude-code"
    monkeypatch.setattr(tools, "is_installed", installed(True))
    out = ready(entry, tmp_path, signed_in={"claude": False})
    assert (out.state, out.command) == (State.NEEDS_SIGN_IN, "claude auth login")
    assert ready(entry, tmp_path, signed_in={"claude": True}).state is State.READY
    # A CLI that cannot say is given the benefit of the doubt: the test connection decides.
    assert ready(entry, tmp_path, signed_in={"claude": None}).state is State.READY


def test_codex_asks_for_its_own_sign_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "is_installed", installed(True))
    out = ready(known("codex_cli"), tmp_path, signed_in={"codex": False})
    assert (out.state, out.command) == (State.NEEDS_SIGN_IN, "codex login")


def test_a_local_model_needs_its_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entry = known("ollama")
    monkeypatch.setattr(service.shutil, "which", on_path(None))
    assert ready(entry, tmp_path).state is State.NEEDS_INSTALL
    monkeypatch.setattr(service.shutil, "which", on_path("/usr/bin/ollama"))
    out = ready(entry, tmp_path)
    assert (out.state, out.command) == (State.NEEDS_SERVER, "ollama serve")
    assert ready(entry, tmp_path, servers=frozenset({"ollama"})).state is State.READY


def test_the_demo_agent_needs_nothing(tmp_path: Path) -> None:
    assert ready(known("demo"), tmp_path).state is State.READY


# --- the catalog never holds a secret --------------------------------------------------------


async def test_the_catalog_says_a_key_is_set_and_never_shows_it(tmp_path: Path) -> None:
    setup = AgentSetup(tmp_path, environ={"OPENAI_API_KEY": "env-" + SECRET})
    setup.set_key("anthropic", SECRET)
    catalog = await setup.catalog()
    text = catalog.model_dump_json(by_alias=True)
    assert SECRET not in text
    assert "env-" + SECRET not in text
    views = {view.id: view for view in catalog.presets}
    assert (views["anthropic"].key.set, views["anthropic"].key.source) == (True, "saved")
    assert views["anthropic"].key.last4 == SECRET[-4:]
    assert (views["openai"].key.source, views["openai"].key.last4) == ("environment", None)
    assert views["claude_code"].key.set is False


async def test_a_short_key_shows_no_part_of_itself(tmp_path: Path) -> None:
    setup = AgentSetup(tmp_path, environ={})
    setup.set_key("anthropic", "short-key-1234")
    views = {view.id: view for view in (await setup.catalog()).presets}
    assert views["anthropic"].key.last4 is None


async def test_the_catalog_speaks_camel_case_and_lists_what_a_local_server_offers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def servers() -> list[probes.LocalServer]:
        return [probes.LocalServer("Ollama", "ollama", "http://127.0.0.1:11434/v1", ("qwen3:4b",))]

    monkeypatch.setattr(probes, "local_servers", servers)
    wire = json.loads(
        (await AgentSetup(tmp_path, environ={}).catalog()).model_dump_json(by_alias=True)
    )
    assert wire["local"] == [
        {
            "name": "Ollama",
            "preset": "ollama",
            "baseUrl": "http://127.0.0.1:11434/v1",
            "models": ["qwen3:4b"],
        }
    ]
    ollama = next(entry for entry in wire["presets"] if entry["id"] == "ollama")
    assert ollama["readiness"]["state"] == "ready"
    assert {"needsKey", "editableUrl", "keyEnv", "baseUrl"} <= set(ollama)


# --- turning a choice into the host's request ------------------------------------------------


def test_a_choice_without_what_it_needs_is_refused() -> None:
    with pytest.raises(AgentSetupError, match="API key"):
        config_for(known("anthropic"), Choice(preset="anthropic"), None)
    with pytest.raises(AgentSetupError, match="endpoint"):
        config_for(known("custom"), Choice(preset="custom", model="m"), None)
    with pytest.raises(AgentSetupError, match="model"):
        config_for(known("custom"), Choice(preset="custom", base_url="http://x/v1"), None)
    with pytest.raises(AgentSetupError, match="whole number"):
        config_for(known("ollama"), Choice(preset="ollama", context_window="lots"), None)


def test_a_complete_choice_becomes_a_configure_request() -> None:
    config = config_for(
        known("ollama"),
        Choice(preset="ollama", model="qwen3:4b", context_window="16000", fast_model="off"),
        None,
    )
    assert (config.provider, config.model, config.context_window) == ("openai", "qwen3:4b", 16000)
    assert config.base_url == "http://127.0.0.1:11434/v1"
    assert config.api_key is None
    assert config.fast_model == "off"
    keyed = config_for(known("anthropic"), Choice(preset="anthropic"), SECRET)
    assert keyed.api_key is not None
    assert keyed.api_key.get_secret_value() == SECRET
    assert keyed.model == known("anthropic").models[0]


def test_using_a_provider_needs_its_key_to_be_saved_or_in_the_environment(tmp_path: Path) -> None:
    setup = AgentSetup(tmp_path, environ={})
    with pytest.raises(AgentSetupError, match="API key"):
        setup.use(Choice(preset="anthropic"))
    setup.set_key("anthropic", SECRET)
    setup.use(Choice(preset="anthropic"))
    assert setup.store.current().preset == "anthropic"


def test_an_unknown_provider_is_refused(tmp_path: Path) -> None:
    with pytest.raises(AgentSetupError, match="unknown provider"):
        AgentSetup(tmp_path, environ={}).use(Choice(preset="nothing"))


async def test_the_test_asks_the_provider_and_reports(tmp_path: Path) -> None:
    message = await AgentSetup(tmp_path, environ={}).test(Choice(preset="demo"))
    assert message.startswith("answered in")


async def test_a_failing_test_says_why(tmp_path: Path) -> None:
    with pytest.raises(AgentSetupError, match="API key"):
        await AgentSetup(tmp_path, environ={}).test(Choice(preset="anthropic"))


# --- what the computer is asked --------------------------------------------------------------


def test_models_are_read_from_ollama_and_from_openai_compatible_servers() -> None:
    assert probes.models_in({"models": [{"name": "qwen3:4b"}, {"name": "llama3"}]}) == (
        "qwen3:4b",
        "llama3",
    )
    assert probes.models_in({"data": [{"id": "local-model"}, {"object": "x"}]}) == ("local-model",)
    assert probes.models_in("not an object") == ()
    assert probes.models_in({"models": "nope"}) == ()


# --- the command line ------------------------------------------------------------------------


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PLURAL_DATA_DIR", str(tmp_path))
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def test_the_command_line_saves_a_key_from_stdin_and_never_prints_it(data_dir: Path) -> None:
    result = runner.invoke(app, ["agent", "key", "anthropic"], input=f"{SECRET}\n")
    assert result.exit_code == 0, result.output
    assert SECRET not in result.output
    assert AgentStore(data_dir).key("anthropic") == SECRET
    forgotten = runner.invoke(app, ["agent", "key", "anthropic", "--clear"])
    assert forgotten.exit_code == 0
    assert AgentStore(data_dir).key("anthropic") is None


def test_use_refuses_what_is_not_ready_and_saves_what_is(data_dir: Path) -> None:
    refused = runner.invoke(app, ["agent", "use", "anthropic"])
    assert refused.exit_code == 1
    assert "API key" in refused.output
    saved = runner.invoke(app, ["agent", "use", "ollama", "--model", "qwen3:4b", "--fast", "off"])
    assert saved.exit_code == 0, saved.output
    current = AgentStore(data_dir).current()
    assert (current.preset, current.model, current.fast_model) == ("ollama", "qwen3:4b", "off")


def test_the_list_is_machine_readable(data_dir: Path) -> None:
    result = runner.invoke(app, ["agent", "list", "--json"])
    assert result.exit_code == 0, result.output
    wire = json.loads(result.output)
    assert wire["current"]["preset"] == "demo"
    assert {entry["id"] for entry in wire["presets"]} >= {"claude_code", "codex_cli", "ollama"}


def test_the_list_is_readable_by_people(data_dir: Path) -> None:
    result = runner.invoke(app, ["agent", "list"])
    assert result.exit_code == 0, result.output
    assert "Claude Code" in result.output
    assert "needs key" in result.output


# --- the relay rooms go through --------------------------------------------------------------


def test_the_relay_the_terminal_client_saved_is_the_computers_relay(tmp_path: Path) -> None:
    (tmp_path / "tui.json").write_text(
        json.dumps({"share": "relay", "relayUrl": "wss://relay.example.org", "theme": "tokyo"}),
        encoding="utf-8",
    )
    store = AgentStore(tmp_path)
    assert store.relay() == "wss://relay.example.org"
    store.set_relay("  wss://other.example.org/  ")
    saved = json.loads((tmp_path / "tui.json").read_text(encoding="utf-8"))
    assert (saved["relayUrl"], saved["share"], saved["theme"]) == (
        "wss://other.example.org/",
        "relay",
        "tokyo",
    )
    store.set_relay("")
    assert store.relay() == ""


def test_a_computer_that_shares_another_way_has_no_relay_of_its_own(tmp_path: Path) -> None:
    (tmp_path / "tui.json").write_text(
        json.dumps({"share": "network", "relayUrl": "wss://relay.example.org"}), encoding="utf-8"
    )
    assert AgentStore(tmp_path).relay() == ""


@pytest.mark.parametrize(
    "bad", ["https://relay.example.org", "relay.example.org", "wss://", "wss://u:p@relay.example"]
)
def test_an_address_that_is_not_a_relay_is_refused(tmp_path: Path, bad: str) -> None:
    with pytest.raises(AgentSetupError):
        AgentStore(tmp_path).set_relay(bad)
