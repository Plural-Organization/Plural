import asyncio
import stat
from collections.abc import AsyncIterator, Mapping
from pathlib import Path

import pytest

from plural.bridge.config import BridgeConfig, ConfigError
from plural.bridge.model import Answer, Incoming, Notice, Person, Place, Pressed
from plural.bridge.platform import AuthError, PlatformError
from plural.bridge.registry import NAMES, Field, Provider, Registry
from plural.bridge.service import BridgeService, State
from plural.protocol.commands import ClientInfo


class Quiet:
    """A chat service that connects and then hears nothing."""

    name = "quiet"
    identity = "@quiet_bot"

    def __init__(self, values: Mapping[str, str]) -> None:
        self.values = dict(values)
        self.closed = False

    async def start(self) -> None:
        if self.values.get("token") == "bad":
            raise AuthError("rejected")
        if self.values.get("token") == "down":
            raise PlatformError("network: unreachable")

    async def incoming(self) -> AsyncIterator[Incoming]:
        await asyncio.Event().wait()
        yield Pressed(Place("quiet", "1"), Person("1", "x"), "x")

    async def show(
        self,
        place: Place,
        key: str,
        view: Answer | Notice,
        *,
        final: bool = True,
        reply_to: str | None = None,
    ) -> None:
        return None

    async def answer(self, pressed: Pressed, text: str = "", *, alert: bool = False) -> None:
        return None

    async def close(self) -> None:
        self.closed = True


QUIET = Provider(
    id="quiet",
    label="Quiet",
    summary="A test service.",
    fields=(Field("token", "Token", secret=True), NAMES),
    build=lambda values: Quiet(values),
)


def service(tmp_path: Path, *, retry_s: float = 0.05, watch_s: float = 0.05) -> BridgeService:
    registry = Registry()
    registry.register(QUIET)
    return BridgeService(
        tmp_path,
        rooms=lambda: [],
        client=ClientInfo(kind="test", version="0"),
        registry=registry,
        retry_s=retry_s,
        watch_s=watch_s,
    )


def only(catalog: list[dict[str, object]]) -> dict[str, object]:
    assert len(catalog) == 1
    return catalog[0]


def test_the_catalog_describes_a_provider_and_never_returns_a_secret(tmp_path: Path) -> None:
    bridges = service(tmp_path)
    assert only(bridges.catalog())["configured"] is False

    bridges.save("quiet", {"token": "s3cret-value", "names": "bot, helper"}, enabled=False)
    entry = only(bridges.catalog())

    assert entry["configured"] is True
    assert entry["set"] == ["token", "names"]
    assert entry["values"] == {"token": "", "names": "bot, helper"}
    assert "s3cret-value" not in str(bridges.catalog())


def test_the_config_file_is_private_and_a_blank_secret_keeps_the_saved_one(tmp_path: Path) -> None:
    config = BridgeConfig(tmp_path)
    config.save(QUIET, {"token": "keep-me"})

    config.save(QUIET, {"token": "", "names": "x"})

    entry = config.get("quiet")
    assert entry is not None
    assert entry.values["token"] == "keep-me"
    assert stat.S_IMODE(config.path.stat().st_mode) == 0o600
    assert BridgeConfig(tmp_path).get("quiet") == entry


def test_a_required_field_and_an_unknown_one_are_refused(tmp_path: Path) -> None:
    config = BridgeConfig(tmp_path)

    with pytest.raises(ConfigError, match="Token is required"):
        config.save(QUIET, {"names": "x"})
    with pytest.raises(ConfigError, match="no setting called nope"):
        config.save(QUIET, {"token": "a", "nope": "b"})


async def test_saving_starts_the_bridge_and_removing_stops_it(tmp_path: Path) -> None:
    bridges = service(tmp_path)
    assert bridges.start()

    bridges.save("quiet", {"token": "good"})
    await _until(bridges, "state", State.RUNNING)
    assert only(bridges.catalog())["identity"] == "@quiet_bot"

    bridges.remove("quiet")
    assert only(bridges.catalog())["configured"] is False
    await bridges.stop()


async def test_a_refused_token_fails_for_good_and_a_dropped_network_is_retried(
    tmp_path: Path,
) -> None:
    bridges = service(tmp_path)
    assert bridges.start()

    bridges.save("quiet", {"token": "bad"})
    await _until(bridges, "state", State.FAILED)
    assert only(bridges.catalog())["error"] == "rejected"

    bridges.save("quiet", {"token": "down"})
    await _until(bridges, "error", "network: unreachable")
    assert only(bridges.catalog())["state"] in {State.FAILED.value, State.STARTING.value}

    bridges.save("quiet", {"token": "good"})
    await _until(bridges, "state", State.RUNNING)
    await bridges.stop()


async def test_a_disabled_provider_does_not_run(tmp_path: Path) -> None:
    bridges = service(tmp_path)
    assert bridges.start()

    bridges.save("quiet", {"token": "good"}, enabled=False)
    await asyncio.sleep(0.1)
    await bridges.stop()

    assert only(bridges.catalog())["state"] == "off"
    assert only(bridges.catalog())["enabled"] is False


async def test_test_connects_once_with_typed_values_and_saves_nothing(tmp_path: Path) -> None:
    bridges = service(tmp_path)

    assert await bridges.test("quiet", {"token": "good"}) == "@quiet_bot"
    with pytest.raises(AuthError):
        await bridges.test("quiet", {"token": "bad"})
    with pytest.raises(ConfigError, match="Token is required"):
        await bridges.test("quiet", {})
    assert only(bridges.catalog())["configured"] is False


def test_pairing_shows_until_there_is_an_owner_and_can_be_renewed(tmp_path: Path) -> None:
    bridges = service(tmp_path)
    bridges.save("quiet", {"token": "good"}, enabled=False)
    first = only(bridges.catalog())["pairing"]
    assert isinstance(first, str)
    assert len(first) == 6

    renewed = bridges.renew_pairing("quiet")

    assert renewed != first or len(renewed) == 6
    with pytest.raises(ConfigError, match="unknown chat service"):
        bridges.renew_pairing("nowhere")


async def _until(bridges: BridgeService, field: str, wanted: object) -> None:
    async with asyncio.timeout(5):
        while only(bridges.catalog())[field] != wanted:
            await asyncio.sleep(0.01)


async def test_a_second_process_edits_the_settings_and_the_first_one_runs_them(
    tmp_path: Path,
) -> None:
    runner = service(tmp_path)
    editor = service(tmp_path)
    assert runner.start()
    assert not editor.start()

    editor.save("quiet", {"token": "good"})

    await _until(runner, "state", State.RUNNING)
    # The editor sees what the runner says about it, through the status file.
    await _until(editor, "state", State.RUNNING)
    assert only(editor.catalog())["identity"] == "@quiet_bot"

    editor.save("quiet", {"token": "bad"})
    await _until(runner, "state", State.FAILED)
    editor.remove("quiet")
    await _until(runner, "configured", False)
    await runner.stop()


async def test_the_editor_sees_idle_when_nothing_runs_the_bridges(tmp_path: Path) -> None:
    editor = service(tmp_path)

    editor.save("quiet", {"token": "good"})

    assert only(editor.catalog())["state"] == "idle"
