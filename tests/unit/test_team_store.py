import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from plural.host.team import TeamError, TeamProfile, TeamStore
from plural.protocol.team import MemberView, TeamRole

JOINED = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def team(team_id: str, name: str) -> TeamProfile:
    member = MemberView(id="m_me", name="alia", key="k", role=TeamRole.MEMBER, joined_at=JOINED)
    return TeamProfile(
        relay="wss://relay.example",
        team_id=team_id,
        team_name=name,
        team_key="K",
        certificate="C",
        member=member,
    )


def test_a_computer_keeps_several_teams_and_the_one_plural_team_made(tmp_path: Path) -> None:
    store = TeamStore(tmp_path)
    store.save(team("t_legacy", "Zeta"))
    store.keep(team("t_a", "alpha"))
    store.keep(team("t_b", "Backend"))
    assert [profile.team_id for profile in store.profiles()] == ["t_a", "t_b", "t_legacy"]
    assert TeamStore(tmp_path, "t_b").load() == team("t_b", "Backend")
    # The team in team.json is found by its id too.
    assert TeamStore(tmp_path, "t_legacy").load() == team("t_legacy", "Zeta")
    assert TeamStore(tmp_path, "t_none").load() is None
    assert store.load() == team("t_legacy", "Zeta")


def test_a_store_bound_to_a_team_renews_into_that_teams_file(tmp_path: Path) -> None:
    TeamStore(tmp_path).keep(team("t_a", "Alpha"))
    bound = TeamStore(tmp_path, "t_a")
    renewed = team("t_a", "Alpha").model_copy(update={"certificate": "C2"})
    bound.save(renewed)
    assert TeamStore(tmp_path, "t_a").load() == renewed
    assert TeamStore(tmp_path).load() is None


@pytest.mark.parametrize("bad", ["../x", "a/b", "", "x" * 65])
def test_a_team_id_cannot_name_a_path(tmp_path: Path, bad: str) -> None:
    with pytest.raises(TeamError):
        TeamStore(tmp_path, bad)
    with pytest.raises(TeamError):
        TeamStore(tmp_path).keep(team(bad, "Evil"))


def test_the_first_second_team_moves_team_json_and_keeps_it_current(tmp_path: Path) -> None:
    store = TeamStore(tmp_path)
    store.save(team("t_old", "Backend"))
    store.add(team("t_new", "Infra"))
    assert not (tmp_path / "team.json").exists()
    assert store.load() == team("t_new", "Infra")
    assert [profile.team_id for profile in store.profiles()] == ["t_old", "t_new"]
    assert store.use("t_old") == team("t_old", "Backend")
    assert store.load() == team("t_old", "Backend")
    with pytest.raises(TeamError):
        store.use("t_gone")


def test_leaving_the_current_team_leaves_no_current_one(tmp_path: Path) -> None:
    store = TeamStore(tmp_path)
    store.add(team("t_a", "Alpha"))
    store.add(team("t_b", "Beta"))
    store.clear()
    assert store.load() is None
    assert [profile.team_id for profile in store.profiles()] == ["t_a"]
    assert TeamStore(tmp_path, "t_a").load() == team("t_a", "Alpha")


def test_the_command_line_lists_teams_and_switches_between_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from plural.cli.main import app

    monkeypatch.setenv("PLURAL_DATA_DIR", str(tmp_path))
    store = TeamStore(tmp_path)
    store.add(team("t_a", "Alpha"))
    store.add(team("t_b", "Beta"))
    runner = CliRunner()
    listed = runner.invoke(app, ["team", "list", "--json"])
    assert listed.exit_code == 0, listed.output
    rows = json.loads(listed.output)
    assert [(row["name"], row["current"]) for row in rows] == [("Alpha", False), ("Beta", True)]
    switched = runner.invoke(app, ["team", "use", "alpha"])
    assert switched.exit_code == 0, switched.output
    assert TeamStore(tmp_path).load() == team("t_a", "Alpha")
    missing = runner.invoke(app, ["team", "use", "gamma"])
    assert missing.exit_code == 1
