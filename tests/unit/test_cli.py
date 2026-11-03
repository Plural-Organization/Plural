import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import uvicorn
from typer.testing import CliRunner

from plural import __version__
from plural.cli import main
from plural.cli.main import app
from plural.host.config import DEFAULT_RELAY_URL, HostSettings
from plural.host.team import TeamProfile, TeamStore
from plural.protocol.envelope import PROTOCOL_VERSION
from plural.protocol.events import ParticipantLeft
from plural.protocol.models import PromptMode
from plural.protocol.team import MemberView, TeamRole
from plural.relay import app as relay_app
from plural.relay.limits import RelayLimits
from plural.storage.sqlite_store import SqliteEventStore

runner = CliRunner()


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "PLURAL_PROVIDER", "PLURAL_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PLURAL_DATA_DIR", str(tmp_path / "data"))


def test_doctor_passes_with_the_demo_provider(tmp_path: Path) -> None:
    result = runner.invoke(app, ["doctor", "--workspace", str(tmp_path)])
    assert result.exit_code == 0
    assert "demo agent" in result.output


def test_doctor_fails_without_a_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PLURAL_PROVIDER", "anthropic")
    result = runner.invoke(app, ["doctor", "--workspace", str(tmp_path)])
    assert result.exit_code == 1
    assert "ANTHROPIC_API_KEY" in result.output


def test_doctor_accepts_the_vendor_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PLURAL_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert runner.invoke(app, ["doctor", "--workspace", str(tmp_path)]).exit_code == 0


def test_export_writes_one_line_per_event(tmp_path: Path) -> None:
    async def populate() -> None:
        store = await SqliteEventStore.open(tmp_path / "data" / "sessions" / "r_demo.db")
        for index in range(3):
            await store.append(
                ParticipantLeft(participant_id=f"p_{index}"),
                event_id=f"e_{index}",
                ts=datetime(2026, 10, 25, tzinfo=UTC),
                actor_id=None,
            )
        await store.close()

    asyncio.run(populate())
    out = tmp_path / "session.jsonl"
    result = runner.invoke(app, ["export", "r_demo", "--out", str(out)])
    assert result.exit_code == 0
    assert len(out.read_text().splitlines()) == 3


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ([], None),
        (["--prompts", "review"], PromptMode.REVIEW),
        (["--prompts", "open"], PromptMode.OPEN),
    ],
)
def test_host_passes_the_prompt_mode_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    arguments: list[str],
    expected: PromptMode | None,
) -> None:
    seen: list[HostSettings] = []

    async def fake_host(settings: HostSettings, *, machine: bool) -> None:
        seen.append(settings)

    monkeypatch.setattr(main, "_host", fake_host)
    result = runner.invoke(app, ["host", "--workspace", str(tmp_path), *arguments])
    assert result.exit_code == 0
    assert [settings.prompt_mode for settings in seen] == [expected]


def test_ready_line_is_one_json_object() -> None:
    line = main.ready_line("r_1", "ws://h/r_1?invite=a", "ws://h/r_1?token=t")
    assert "\n" not in line
    assert json.loads(line) == {
        "type": "ready",
        "room": "r_1",
        "guest_link": "ws://h/r_1?invite=a",
        "host_link": "ws://h/r_1?token=t",
        "version": __version__,
        "protocol": PROTOCOL_VERSION,
    }


def test_host_rejects_an_unknown_prompt_mode(tmp_path: Path) -> None:
    result = runner.invoke(app, ["host", "--workspace", str(tmp_path), "--prompts", "closed"])
    assert result.exit_code == 2


def test_plain_links_keep_each_link_on_one_line() -> None:
    host_link = "wss://relay.example.com/r_1?token=" + "t" * 300
    lines = main.plain_links("r_1", "wss://relay.example.com/r_1?invite=a", host_link).splitlines()
    assert lines == [
        "room r_1",
        "room link (the host lets people in): wss://relay.example.com/r_1?invite=a",
        f"host link: {host_link}",
    ]


def host_settings(monkeypatch: pytest.MonkeyPatch, arguments: list[str]) -> HostSettings:
    seen: list[HostSettings] = []

    async def fake_host(settings: HostSettings, *, machine: bool) -> None:
        seen.append(settings)

    monkeypatch.setattr(main, "_host", fake_host)
    assert runner.invoke(app, ["host", *arguments]).exit_code == 0
    return seen[0]


def test_host_reads_its_address_settings_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PLURAL_RELAY_URL", "wss://relay.example.com")
    monkeypatch.setenv("PLURAL_PORT", "9100")
    monkeypatch.setenv("PLURAL_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("PLURAL_ROOM", "r_env")
    monkeypatch.setenv("PLURAL_HOST_NAME", "ci")
    settings = host_settings(monkeypatch, ["--workspace", str(tmp_path)])
    assert settings.relay_url == "wss://relay.example.com"
    assert settings.port == 9100
    assert settings.bind_host == "0.0.0.0"
    assert settings.room == "r_env"
    assert settings.host_name == "ci"


def test_a_flag_wins_over_the_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PLURAL_RELAY_URL", "wss://relay.example.com")
    monkeypatch.setenv("PLURAL_PORT", "9100")
    settings = host_settings(
        monkeypatch,
        ["--workspace", str(tmp_path), "--relay", "wss://other.example.com", "--port", "9200"],
    )
    assert settings.relay_url == "wss://other.example.com"
    assert settings.port == 9200


def clean_address_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in (
        "PLURAL_RELAY_URL",
        "PLURAL_PORT",
        "PLURAL_BIND_HOST",
        "PLURAL_PUBLIC_URL",
        "PLURAL_HOST_NAME",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PLURAL_DATA_DIR", str(tmp_path / "data"))


def test_host_without_an_address_uses_the_plural_relay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clean_address_environment(monkeypatch, tmp_path)
    settings = host_settings(monkeypatch, ["--workspace", str(tmp_path)])
    assert settings.relay_url == DEFAULT_RELAY_URL
    assert settings.host_name != ""


def test_a_host_stays_on_this_machine_when_asked_or_given_its_own_address(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clean_address_environment(monkeypatch, tmp_path)
    workspace = ["--workspace", str(tmp_path)]
    local = host_settings(monkeypatch, [*workspace, "--local"])
    assert (local.relay_url, local.bind_host, local.port) == (None, "127.0.0.1", 7777)
    bound = host_settings(monkeypatch, [*workspace, "--bind", "0.0.0.0"])
    assert bound.relay_url is None
    public = host_settings(monkeypatch, [*workspace, "--public-url", "wss://host.example.com"])
    assert public.relay_url is None
    ported = host_settings(monkeypatch, [*workspace, "--port", "9300"])
    assert ported.relay_url == DEFAULT_RELAY_URL


def test_the_environment_can_give_a_host_its_own_address(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clean_address_environment(monkeypatch, tmp_path)
    monkeypatch.setenv("PLURAL_BIND_HOST", "0.0.0.0")
    assert host_settings(monkeypatch, ["--workspace", str(tmp_path)]).relay_url is None


def test_a_team_host_uses_the_relay_of_its_team(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clean_address_environment(monkeypatch, tmp_path)
    member = MemberView(
        id="m_1", name="ann", key="k", role=TeamRole.OWNER, joined_at=datetime.now(UTC)
    )
    TeamStore(tmp_path / "data").save(
        TeamProfile(
            relay="wss://team.example.com",
            team_id="t_1",
            team_name="core",
            team_key="k",
            certificate="c",
            member=member,
        )
    )
    settings = host_settings(monkeypatch, ["--workspace", str(tmp_path), "--team"])
    assert settings.relay_url == "wss://team.example.com"


def test_relay_listens_on_the_port_the_platform_assigns(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(_app: object, **options: object) -> None:
        seen.update(options)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    monkeypatch.setenv("PORT", "4321")
    monkeypatch.setenv("PLURAL_RELAY_BIND", "0.0.0.0")
    assert runner.invoke(app, ["relay"]).exit_code == 0
    assert (seen["host"], seen["port"]) == ("0.0.0.0", 4321)


def test_the_relay_can_serve_only_plural_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_create_app(_limits: object = None, **options: object) -> object:
        seen.update(options)
        return object()

    def fake_run(_app: object, **_options: object) -> None:
        return None

    monkeypatch.setattr(relay_app, "create_app", fake_create_app)
    monkeypatch.setattr(uvicorn, "run", fake_run)
    monkeypatch.setenv("PLURAL_RELAY_CLIENTS_ONLY", "true")
    monkeypatch.setenv("PLURAL_RELAY_WEB_ORIGINS", "https://a.example, https://b.example ,")
    assert runner.invoke(app, ["relay"]).exit_code == 0
    assert seen["clients_only"] is True
    assert seen["web_origins"] == ["https://a.example", "https://b.example"]


def test_a_relay_for_one_person_can_own_more_teams_per_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[object] = []

    def fake_create_app(_limits: object = None, **options: object) -> object:
        seen.append(options["team_limits"])
        return object()

    def fake_run(_app: object, **_options: object) -> None:
        return None

    monkeypatch.setattr(relay_app, "create_app", fake_create_app)
    monkeypatch.setattr(uvicorn, "run", fake_run)
    assert runner.invoke(app, ["relay"]).exit_code == 0
    assert runner.invoke(app, ["relay", "--teams-per-owner", "1000"]).exit_code == 0
    assert [getattr(limits, "max_teams_per_owner") for limits in seen] == [3, 1000]  # noqa: B009


def test_relay_limits_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[RelayLimits | None, int, Path | None]] = []

    def fake_create_app(
        limits: RelayLimits | None = None,
        *,
        proxy_hops: int = 0,
        teams: Path | None = None,
        **_: object,
    ) -> object:
        seen.append((limits, proxy_hops, teams))
        return object()

    def fake_run(_app: object, **_options: object) -> None:
        return None

    monkeypatch.setattr(relay_app, "create_app", fake_create_app)
    monkeypatch.setattr(uvicorn, "run", fake_run)
    monkeypatch.setenv("PLURAL_RELAY_MAX_ROOMS", "7")
    monkeypatch.setenv("PLURAL_RELAY_ROOMS_PER_PEER", "2")
    monkeypatch.setenv("PLURAL_RELAY_GUESTS_PER_PEER", "9")
    monkeypatch.setenv("PLURAL_RELAY_PROXY_HOPS", "1")
    monkeypatch.setenv("PLURAL_RELAY_TEAMS", "/data/teams.db")
    assert runner.invoke(app, ["relay"]).exit_code == 0
    assert seen == [
        (
            RelayLimits(max_rooms=7, max_rooms_per_peer=2, max_guests_per_peer=9),
            1,
            Path("/data/teams.db"),
        )
    ]
