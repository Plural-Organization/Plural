import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest
from typer.testing import CliRunner

from plural import __version__
from plural.cli.main import app
from plural.host import team
from plural.host.relay_http import ConnectFailed
from plural.host.team import TeamError, TeamProfile, TeamStore
from plural.protocol.team import MemberView, TeamRole


class _Response(io.BytesIO):
    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def test_directory_requests_identify_plural_not_python_urllib(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A relay behind Cloudflare refuses the default "Python-urllib" agent with error 1010.
    seen: list[Request] = []

    def fake_urlopen(request: Request, **_: Any) -> _Response:
        seen.append(request)
        return _Response(b"{}")

    monkeypatch.setattr(team, "urlopen", fake_urlopen)
    team._call(  # pyright: ignore[reportPrivateUsage]
        "POST", "https://relay.example/teams", b"{}", {"content-type": "application/json"}
    )

    assert seen[0].get_header("User-agent") == f"plural/{__version__}"
    assert seen[0].get_header("Content-type") == "application/json"


def test_a_connection_that_never_opened_is_tried_once_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def flaky(request: Request, **_: Any) -> _Response:
        calls.append(1)
        if len(calls) == 1:
            raise URLError(ConnectFailed("no answer"))
        return _Response(b'{"ok":true}')

    monkeypatch.setattr(team, "urlopen", flaky)
    assert team._call("GET", "https://relay.example/teams", None, {}) == {"ok": True}  # pyright: ignore[reportPrivateUsage]
    assert len(calls) == 2


def test_a_request_that_may_have_been_sent_is_not_repeated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def slow(request: Request, **_: Any) -> _Response:
        calls.append(1)
        raise URLError(TimeoutError("timed out"))

    monkeypatch.setattr(team, "urlopen", slow)
    with pytest.raises(TeamError, match="did not answer, try again in a moment"):
        team._call("POST", "https://relay.example/teams", b"{}", {})  # pyright: ignore[reportPrivateUsage]
    assert len(calls) == 1


def test_two_failed_connections_say_the_relay_did_not_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _answer(monkeypatch, URLError(ConnectFailed("no answer")))
    with pytest.raises(TeamError, match="did not answer, try again in a moment"):
        team._call("GET", "https://relay.example/teams", None, {})  # pyright: ignore[reportPrivateUsage]


def _profile(relay: str) -> TeamProfile:
    member = MemberView(
        id="m_1", name="ann", key="k", role=TeamRole.OWNER, joined_at=datetime.now(UTC)
    )
    return TeamProfile(
        relay=relay,
        team_id="t_1",
        team_name="core",
        team_key="k",
        certificate="c",
        member=member,
    )


def _answer(monkeypatch: pytest.MonkeyPatch, outcome: int | Exception) -> None:
    def fake_urlopen(request: Request, **_: Any) -> _Response:
        if isinstance(outcome, Exception):
            raise outcome
        if outcome != 200:
            raise HTTPError(request.full_url, outcome, "gone", {}, io.BytesIO(b"<html>gone</html>"))  # pyright: ignore[reportArgumentType]
        return _Response(b'{"ok":true}')

    monkeypatch.setattr(team, "urlopen", fake_urlopen)


def test_only_tunnels_that_open_for_one_session_are_told_apart() -> None:
    for host in ("calm.trycloudflare.com", "a1.ngrok-free.app", "x.ngrok.io", "abc.loca.lt:443"):
        assert team.is_tunnel_host(host)
    for host in ("relay.plrl.host", "relay.example.com", "127.0.0.1:8787", "notngrok.io"):
        assert not team.is_tunnel_host(host)


def test_a_relay_is_gone_only_when_something_else_answers_for_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _answer(monkeypatch, 200)
    assert team.relay_state("wss://r.example.com") == "alive"
    _answer(monkeypatch, 530)
    assert team.relay_state("wss://r.example.com") == "dead"
    _answer(monkeypatch, URLError("offline"))
    assert team.relay_state("wss://r.example.com") == "unknown"


def test_a_closed_tunnel_is_named_not_shown_as_a_relay_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _answer(monkeypatch, 530)
    with pytest.raises(TeamError, match=r"tunnel gone\.trycloudflare\.com is closed"):
        team._call("GET", "https://gone.trycloudflare.com/teams/t_1", None, {})  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(TeamError, match="the relay answered 530"):
        team._call("GET", "https://relay.example.com/teams/t_1", None, {})  # pyright: ignore[reportPrivateUsage]


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TeamStore:
    monkeypatch.setenv("PLURAL_DATA_DIR", str(tmp_path))
    return TeamStore(tmp_path)


def test_a_team_whose_tunnel_closed_is_left_instead_of_blocking_a_new_one(
    monkeypatch: pytest.MonkeyPatch, home: TeamStore
) -> None:
    home.save(_profile("wss://gone.trycloudflare.com"))
    _answer(monkeypatch, 530)
    result = CliRunner().invoke(app, ["team", "leave"])
    assert result.exit_code == 0
    assert "tunnel is closed" in result.output
    assert home.load() is None


def test_a_closed_tunnel_does_not_stop_creating_another_team(
    monkeypatch: pytest.MonkeyPatch, home: TeamStore
) -> None:
    home.save(_profile("wss://gone.trycloudflare.com"))
    _answer(monkeypatch, 530)
    result = CliRunner().invoke(app, ["team", "create", "again", "--relay", "wss://r.example.com"])
    assert "already in" not in result.output
    assert "You left core" in result.output


@pytest.mark.parametrize(
    ("relay", "outcome"),
    [
        ("wss://up.trycloudflare.com", 200),
        ("wss://gone.trycloudflare.com", URLError("offline")),
        ("wss://relay.example.com", 530),
    ],
)
def test_a_team_is_kept_when_its_tunnel_answers_the_machine_is_offline_or_it_is_no_tunnel(
    monkeypatch: pytest.MonkeyPatch, home: TeamStore, relay: str, outcome: int | Exception
) -> None:
    home.save(_profile(relay))
    _answer(monkeypatch, outcome)
    assert CliRunner().invoke(app, ["team", "status"]).exit_code == 0
    assert home.load() is not None
