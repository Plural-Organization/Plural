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
