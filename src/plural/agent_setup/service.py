"""What each provider still needs, the agent a computer is set to, and a connection test."""

import asyncio
import os
import shutil
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, SecretStr
from pydantic.alias_generators import to_camel

from plural.agent.providers.base import ProviderError
from plural.agent.providers.catalog import PRESETS, Preset, preset
from plural.agent.providers.cli.agents import AGENT_CLIS
from plural.agent_setup import probes
from plural.agent_setup.store import AgentSetupError, AgentStore, Choice
from plural.host import extras, tools
from plural.host.config import HostSettings
from plural.host.control import AgentConfig, probe, provider_for
from plural.host.providers import ConfigError

LAST_CHARS: Final = 4
LAST_CHARS_MIN_KEY: Final = 20
_OAUTH_FILE: Final = "anthropic-oauth.json"


class State(StrEnum):
    READY = "ready"
    NEEDS_KEY = "needs_key"
    NEEDS_INSTALL = "needs_install"  # a CLI
    NEEDS_SDK = "needs_sdk"  # an optional Python extra of plural-agent
    NEEDS_SIGN_IN = "needs_sign_in"
    NEEDS_SERVER = "needs_server"  # a local model server that is not running


class View(BaseModel):
    """What a client is told. camelCase on the wire, as the catalog always was."""

    model_config = ConfigDict(frozen=True, alias_generator=to_camel, populate_by_name=True)


class Readiness(View):
    state: State
    detail: str = ""
    command: str | None = None  # what to run in a terminal to fix it


class KeyFacts(View):
    set: bool
    source: Literal["saved", "environment"] | None = None
    last4: str | None = None


class PresetView(View):
    id: str
    label: str
    provider: str
    base_url: str
    needs_key: bool
    editable_url: bool
    context_window: bool
    models: tuple[str, ...]
    hint: str
    connection: str
    key_env: tuple[str, ...]
    extra: str | None
    tool: str | None
    readiness: Readiness
    key: KeyFacts
    saved: Choice | None


class LocalView(View):
    name: str
    preset: str
    base_url: str
    models: tuple[str, ...]


class Catalog(View):
    presets: tuple[PresetView, ...]
    current: Choice
    local: tuple[LocalView, ...]
    tools: tuple[dict[str, object], ...]


READY: Final = Readiness(state=State.READY)


def key_source(
    entry: Preset, store: AgentStore, environ: Mapping[str, str]
) -> tuple[str, str] | None:
    """Where a provider's key comes from, and the key. The saved key comes first."""
    saved = store.key(entry.id)
    if saved:
        return "saved", saved
    for name in entry.key_env:
        if environ.get(name):
            return "environment", environ[name]
    return None


def _oauth_saved(directory: Path) -> bool:
    return (directory / _OAUTH_FILE).is_file()


def readiness_of(
    entry: Preset,
    store: AgentStore,
    directory: Path,
    environ: Mapping[str, str],
    signed_in: Mapping[str, bool | None],
    servers: frozenset[str] = frozenset(),
) -> Readiness:
    adapter = entry.adapter
    if adapter == "fake":
        return READY
    if entry.id == "ollama" and "ollama" not in servers:
        if shutil.which("ollama") is None:
            return Readiness(
                state=State.NEEDS_INSTALL,
                detail="Ollama is not installed",
                command="https://ollama.com/download",
            )
        return Readiness(
            state=State.NEEDS_SERVER, detail="Ollama is not running", command="ollama serve"
        )
    tool = tools.tool_for(adapter)
    if tool is not None:
        spec = next(spec for spec in tools.SPECS if spec.id == tool)
        if not tools.is_installed(tool):
            return Readiness(
                state=State.NEEDS_INSTALL,
                detail=f"{spec.label} is not installed",
                command=tools.manual_command(tool),
            )
        if signed_in.get(tool) is False:
            return Readiness(
                state=State.NEEDS_SIGN_IN,
                detail=f"{spec.label} is not signed in",
                command=spec.login,
            )
        return READY
    cli = AGENT_CLIS.get(adapter)  # type: ignore[call-overload]
    if cli is not None:
        if shutil.which(cli.binary) is None:
            return Readiness(
                state=State.NEEDS_INSTALL,
                detail=f"{cli.label} is not installed",
                command=cli.install,
            )
        return Readiness(
            state=State.READY, detail=f"If it answers with a sign-in error: {cli.login}"
        )
    extra = extras.extra_for(adapter)
    if extra is not None and not extras.is_installed(extra):
        return Readiness(
            state=State.NEEDS_SDK, detail=extras.LABELS[extra], command=extras.hint(extra)
        )
    if adapter == "anthropic_oauth":
        if _oauth_saved(directory):
            return READY
        return Readiness(
            state=State.NEEDS_SIGN_IN,
            detail="Sign in with Claude from the terminal client's Model settings",
        )
    if entry.needs_key and key_source(entry, store, environ) is None:
        return Readiness(state=State.NEEDS_KEY, detail=f"{entry.label} needs an API key")
    return READY


def config_for(entry: Preset, choice: Choice, key: str | None) -> AgentConfig:
    """The host's `configure` request for a choice, or why it cannot be one yet."""
    if entry.needs_key and not key:
        raise AgentSetupError(f"{entry.label} needs an API key")
    window = choice.context_window.strip()
    context = int(window) if window.isdecimal() and int(window) > 0 else None
    if entry.context_window and window and context is None:
        raise AgentSetupError("the context window must be a whole number of tokens")
    model = choice.model.strip() or (entry.models[0] if entry.models else None)
    endpoint = (
        (choice.base_url.strip() or entry.base_url or None)
        if entry.editable_url
        else (entry.base_url or None)
    )
    if entry.adapter in ("openai", "codex_cli") and model is None:
        raise AgentSetupError("choose a model")
    if entry.adapter == "openai" and entry.editable_url and endpoint is None:
        raise AgentSetupError("enter the endpoint address")
    return AgentConfig(
        preset=entry.id,
        provider=entry.adapter,
        provider_name=entry.label,
        model=model,
        base_url=endpoint,
        api_key=SecretStr(key) if key else None,
        context_window=context if entry.context_window else None,
        fast_model=choice.fast_model,
    )


def _known(provider_id: str) -> Preset:
    entry = preset(provider_id)
    if entry is None:
        raise AgentSetupError(f"unknown provider {provider_id!r}")
    return entry


class AgentSetup:
    """The one place that knows how this computer's agent is set up. Never returns a secret."""

    def __init__(self, directory: Path, environ: Mapping[str, str] | None = None) -> None:
        self._directory = directory
        self._store = AgentStore(directory)
        self._environ = os.environ if environ is None else environ

    @property
    def store(self) -> AgentStore:
        return self._store

    def _key_facts(self, entry: Preset) -> KeyFacts:
        found = key_source(entry, self._store, self._environ)
        if found is None:
            return KeyFacts(set=False)
        source, key = found
        last = key[-LAST_CHARS:] if source == "saved" and len(key) >= LAST_CHARS_MIN_KEY else None
        return KeyFacts(
            set=True, source="saved" if source == "saved" else "environment", last4=last
        )

    async def catalog(self) -> Catalog:
        claude, codex, local = await asyncio.gather(
            probes.claude_signed_in(), probes.codex_signed_in(), probes.local_servers()
        )
        signed_in = {"claude": claude, "codex": codex}
        return Catalog(
            presets=tuple(
                PresetView(
                    id=entry.id,
                    label=entry.label,
                    provider=entry.adapter,
                    base_url=entry.base_url,
                    needs_key=entry.needs_key,
                    editable_url=entry.editable_url,
                    context_window=entry.context_window,
                    models=entry.models,
                    hint=entry.hint,
                    connection=entry.connection,
                    key_env=entry.key_env,
                    extra=extras.extra_for(entry.adapter),
                    tool=tools.tool_for(entry.adapter),
                    readiness=readiness_of(
                        entry,
                        self._store,
                        self._directory,
                        self._environ,
                        signed_in,
                        frozenset(server.preset for server in local),
                    ),
                    key=self._key_facts(entry),
                    saved=self._store.saved(entry.id),
                )
                for entry in PRESETS
            ),
            current=self._store.current(),
            local=tuple(
                LocalView(name=s.name, preset=s.preset, base_url=s.base_url, models=s.models)
                for s in local
            ),
            tools=tuple(tools.inventory()),
        )

    def _config(self, choice: Choice, key: str | None) -> AgentConfig:
        entry = _known(choice.preset)
        found = key or (key_source(entry, self._store, self._environ) or ("", None))[1]
        return config_for(entry, choice, found)

    def set_key(self, provider_id: str, key: str) -> None:
        self._store.set_key(_known(provider_id).id, key)

    def clear_key(self, provider_id: str) -> None:
        self._store.clear_key(_known(provider_id).id)

    def use(self, choice: Choice) -> None:
        """Make it this computer's agent. It must be complete: a key, a model, an address."""
        self._config(choice, None)
        self._store.choose(choice)

    async def test(self, choice: Choice, key: str | None = None) -> str:
        """Ask the provider one short question. Returns how it went, or raises why it failed."""
        config = self._config(choice, key)
        try:
            provider, _, _ = provider_for(HostSettings(data_dir=self._directory), config)
            return await probe(provider)
        except (ConfigError, ProviderError) as error:
            raise AgentSetupError(str(error)) from None
