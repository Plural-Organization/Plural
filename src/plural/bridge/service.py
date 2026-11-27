"""Runs the chat bridges a person set up, and says how each one is doing.

The service is the one owner of bridge configuration: the web client (through the daemon), the
terminal and the CLI all call it. It keeps one supervised task per enabled provider, restarts it
when the network drops and stops for good when the service refuses the credentials.
"""

import asyncio
import fcntl
import json
import os
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import IO, Final, cast

import structlog

from plural.bridge.bridge import Bridge
from plural.bridge.config import BridgeConfig, ConfigError, Entry
from plural.bridge.platform import AuthError, ChatPlatform, Links, PlatformError
from plural.bridge.providers import builtin
from plural.bridge.registry import Provider, Registry
from plural.bridge.store import BridgeStore
from plural.protocol.commands import ClientInfo
from plural.protocol.running import RunningRoom

log = structlog.get_logger(__name__)

RETRY_FIRST_S: Final = 3.0
RETRY_MAX_S: Final = 60.0
TEST_TIMEOUT_S: Final = 20.0
WATCH_S: Final = 2.0


class BridgeBusy(Exception):
    pass


class State(StrEnum):
    OFF = "off"
    STARTING = "starting"
    RUNNING = "running"
    FAILED = "failed"
    # Nothing is running the bridges: start the daemon or `plural bridge run`.
    IDLE = "idle"


@dataclass(slots=True)
class _Live:
    task: asyncio.Task[None]
    state: State = State.STARTING
    identity: str = ""
    error: str = ""
    links: Links = field(default_factory=Links)
    retry_in: float = field(default=0.0)


class BridgeService:
    def __init__(
        self,
        data_dir: Path,
        *,
        rooms: Callable[[], list[RunningRoom]],
        client: ClientInfo,
        registry: Registry | None = None,
        retry_s: float = RETRY_FIRST_S,
        watch_s: float = WATCH_S,
    ) -> None:
        self._dir = data_dir
        self._rooms = rooms
        self._client = client
        self._registry = registry or builtin()
        self._retry_s = retry_s
        self._watch_s = watch_s
        self._config = BridgeConfig(data_dir)
        self._live: dict[str, _Live] = {}
        self._stores: dict[str, BridgeStore] = {}
        self._lock: IO[bytes] | None = None
        self._watcher: asyncio.Task[None] | None = None
        self._seen: dict[str, Entry | None] = {}

    # What there is, and how it is going

    def catalog(self) -> list[dict[str, object]]:
        return [self._describe(provider) for provider in self._registry.all()]

    def _describe(self, provider: Provider) -> dict[str, object]:
        entry = self._config.get(provider.id)
        live = self._live.get(provider.id)
        store = self._store(provider.id)
        owners = store.owners
        configured = entry is not None
        shown = self._status(provider.id)
        if entry is None or not entry.enabled:
            state = State.OFF
        elif live is not None:
            state = live.state
        else:
            state = State(str(shown.get("state", State.IDLE.value)))
        identity = live.identity if live else str(shown.get("identity", ""))
        error = live.error if live else str(shown.get("error", ""))
        values = entry.values if entry else {}
        links = live.links if live else _links(shown)
        code = store.active_pairing() if owners else store.pairing_code()
        return {
            **provider.to_json(),
            "configured": configured,
            "enabled": bool(entry and entry.enabled),
            "state": state.value,
            "identity": identity if state is State.RUNNING else "",
            "error": error if state in (State.FAILED, State.STARTING) else "",
            # A secret is never sent back, only whether it is set.
            "values": {
                item.id: ("" if item.secret else values.get(item.id, ""))
                for item in provider.fields
            },
            "set": [item.id for item in provider.fields if values.get(item.id)],
            "owners": [{"id": key, "name": name} for key, name in owners.items()],
            "pairing": code,
            # Where to meet the bot. `open` already holds the pairing code when the service can
            # take it from a link, so one click makes the person an owner.
            "links": {
                "open": links.open.replace("{code}", code or "") if state is State.RUNNING else "",
                "invite": links.invite if state is State.RUNNING else "",
                "autopair": links.autopair and code is not None,
            },
            "chats": len(store.places_of_all()),
        }

    # Changes

    def save(
        self, provider_id: str, values: dict[str, str], *, enabled: bool | None = None
    ) -> None:
        provider = self._need(provider_id)
        self._config.save(provider, values, enabled=enabled)
        self._restart(provider_id)

    def set_enabled(self, provider_id: str, enabled: bool) -> None:
        self._need(provider_id)
        self._config.set_enabled(provider_id, enabled)
        self._restart(provider_id)

    def remove(self, provider_id: str) -> None:
        self._need(provider_id)
        self._config.remove(provider_id)
        self._restart(provider_id)

    def renew_pairing(self, provider_id: str) -> str:
        self._need(provider_id)
        return self._store(provider_id).pairing_code(renew=True)

    def unpair(self, provider_id: str, person_id: str) -> None:
        self._need(provider_id)
        self._store(provider_id).unpair(person_id)

    async def test(self, provider_id: str, values: dict[str, str] | None = None) -> str:
        """Connects once with the saved values, overridden by those typed and not saved yet, and
        returns the bot's identity. Nothing is saved and no bridge starts."""
        provider = self._need(provider_id)
        entry = self._config.get(provider_id)
        merged = dict(entry.values) if entry else {}
        merged.update(
            {key: value.strip() for key, value in (values or {}).items() if value.strip()}
        )
        for item in provider.fields:
            if item.required and not merged.get(item.id):
                raise ConfigError(f"{item.label} is required")
        platform = provider.build(merged)
        try:
            async with asyncio.timeout(TEST_TIMEOUT_S):
                await platform.start()
            return platform.identity or provider.label
        except TimeoutError:
            raise PlatformError(f"{provider.label} did not answer in {TEST_TIMEOUT_S:g}s") from None
        finally:
            with suppress(Exception):
                await platform.close()

    # Running

    def start(self) -> bool:
        """Takes the right to run the bridges and starts them. False when another process on this
        computer (the daemon, or `plural bridge run`) already holds it: then this one only edits
        the settings, and takes over once that one stops."""
        held = self._claim()
        if held:
            self._reconcile()
        if self._watcher is None:
            self._watcher = asyncio.create_task(self._watch(), name="bridge:watch")
        return held

    def _claim(self) -> bool:
        if self._lock is None:
            path = self._dir / "bridge" / "supervisor.lock"
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            handle = open(path, "wb")  # noqa: SIM115 - held for as long as this process runs
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                handle.close()
                return False
            self._lock = handle
        return True

    async def stop(self) -> None:
        if self._watcher is not None:
            self._watcher.cancel()
            with suppress(asyncio.CancelledError):
                await self._watcher
            self._watcher = None
        tasks = [live.task for live in self._live.values()]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError, Exception):
                await task
        self._live.clear()
        if self._lock is not None:
            self._publish(clear=True)
            self._lock.close()
            self._lock = None

    async def run(self) -> None:
        """Runs every enabled bridge until cancelled: the headless way, `plural bridge run`."""
        if not self.start():
            await self.stop()
            raise BridgeBusy("another Plural process already runs the chat bridges")
        try:
            await asyncio.Event().wait()
        finally:
            await self.stop()

    async def run_with(self, provider_id: str, platform: ChatPlatform) -> None:
        """Runs one bridge with a platform built by the caller, without saving anything."""
        store = self._store(provider_id)
        await Bridge(platform, store, rooms=self._rooms, client=self._client).run()

    async def _watch(self) -> None:
        while True:
            await asyncio.sleep(self._watch_s)
            try:
                if self._claim():
                    self._reconcile()
            except (ConfigError, OSError) as error:
                log.warning("bridge.watch_failed", error=str(error))

    def _reconcile(self) -> None:
        """Makes what runs match the settings: starts, restarts and stops what changed."""
        wanted = {
            provider_id: entry
            for provider_id in self._config.ids()
            if (entry := self._config.get(provider_id)) is not None
            and entry.enabled
            and self._registry.get(provider_id) is not None
        }
        for provider_id in list(self._live):
            if provider_id not in wanted or self._seen.get(provider_id) != wanted[provider_id]:
                self._stop(provider_id)
        for provider_id, entry in wanted.items():
            if provider_id not in self._live:
                self._seen[provider_id] = entry
                self._begin(provider_id)
        self._publish()

    def _status(self, provider_id: str) -> dict[str, object]:
        """What the process that runs the bridges last said about one of them."""
        try:
            saved = json.loads((self._dir / "bridge" / "status.json").read_text(encoding="utf-8"))
            pid = int(saved["pid"])
            os.kill(pid, 0)
            found = saved["providers"].get(provider_id)
            return cast(dict[str, object], found) if isinstance(found, dict) else {}
        except (OSError, ValueError, KeyError, TypeError):
            return {}

    def _publish(self, *, clear: bool = False) -> None:
        if self._lock is None:
            return
        path = self._dir / "bridge" / "status.json"
        if clear:
            path.unlink(missing_ok=True)
            return
        body = {
            "pid": os.getpid(),
            "providers": {
                provider_id: {
                    "state": live.state.value,
                    "identity": live.identity,
                    "error": live.error,
                    "open": live.links.open,
                    "invite": live.links.invite,
                }
                for provider_id, live in self._live.items()
            },
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(body), encoding="utf-8")
        temporary.replace(path)

    def store(self, provider_id: str) -> BridgeStore:
        return self._store(provider_id)

    def pairing(self, provider_id: str) -> str | None:
        """The code that makes someone an owner, or None once the bot has an owner."""
        self._need(provider_id)
        store = self._store(provider_id)
        return None if store.owners else store.pairing_code()

    def _store(self, provider_id: str) -> BridgeStore:
        if provider_id not in self._stores:
            self._stores[provider_id] = BridgeStore(self._dir, provider_id)
        return self._stores[provider_id]

    def _need(self, provider_id: str) -> Provider:
        provider = self._registry.get(provider_id)
        if provider is None:
            raise ConfigError(f"unknown chat service: {provider_id}")
        return provider

    def _restart(self, provider_id: str) -> None:
        if self._lock is not None:
            self._reconcile()

    def _stop(self, provider_id: str) -> None:
        live = self._live.pop(provider_id, None)
        self._seen.pop(provider_id, None)
        if live is not None:
            live.task.cancel()

    def _begin(self, provider_id: str) -> None:
        if provider_id in self._live:
            return
        task = asyncio.create_task(self._supervise(provider_id), name=f"bridge:{provider_id}")
        self._live[provider_id] = _Live(task)

    async def _supervise(self, provider_id: str) -> None:
        delay = self._retry_s
        while True:
            live = self._live.get(provider_id)
            entry = self._config.get(provider_id)
            provider = self._registry.get(provider_id)
            if live is None or entry is None or provider is None:
                return
            live.state = State.STARTING
            try:
                platform = provider.build(entry.values)
                await platform.start()
                live.state, live.identity, live.error = State.RUNNING, platform.identity, ""
                live.links = platform.links
                delay = self._retry_s
                await Bridge(
                    platform,
                    self._store(provider_id),
                    rooms=self._rooms,
                    client=self._client,
                ).run()
            except AuthError as error:
                live.state, live.error = State.FAILED, str(error)
                log.warning("bridge.refused", provider=provider_id, error=str(error))
                return
            except (PlatformError, OSError) as error:
                live.state, live.error = State.FAILED, str(error)
                log.warning("bridge.failed", provider=provider_id, error=str(error))
            except asyncio.CancelledError:
                raise
            except Exception as error:
                live.state, live.error = State.FAILED, "internal error"
                log.exception("bridge.crashed", provider=provider_id, error=str(error))
            live.retry_in = delay
            await asyncio.sleep(delay)
            delay = min(delay * 2, RETRY_MAX_S)


def _links(shown: dict[str, object]) -> Links:
    return Links(open=str(shown.get("open", "")), invite=str(shown.get("invite", "")))
