from datetime import UTC, datetime
from pathlib import Path

from plural.host.repo import name_from_remote
from plural.protocol.models import JoinRequestView, Participant, Role, SessionState
from plural.protocol.team import (
    CardDraft,
    Endpoint,
    EndpointKind,
    MemberClaims,
    SessionStatus,
    TeamRole,
)
from plural.relay.presence import Presence

NOW = datetime(2026, 10, 29, tzinfo=UTC)


def claims(team: str = "t_1", member: str = "m_a", name: str = "alia") -> MemberClaims:
    return MemberClaims(
        team=team, member=member, key="k", name=name, role=TeamRole.MEMBER, iat=NOW, exp=NOW
    )


def draft(room: str = "r_1", status: SessionStatus = SessionStatus.IDLE) -> CardDraft:
    return CardDraft(
        room=room,
        repo="plural",
        branch="main",
        status=status,
        endpoints=(Endpoint(kind=EndpointKind.RELAY, url="wss://relay.example/r_1"),),
    )


class Tick:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_a_published_card_carries_the_owner_from_the_certificate() -> None:
    presence = Presence()
    assert presence.publish(claims(), draft(), object(), NOW)
    (card,) = presence.sessions("t_1", NOW)
    assert (card.owner, card.owner_id, card.room, card.updated_at) == ("alia", "m_a", "r_1", NOW)


def test_a_card_is_gone_after_its_time_to_live_unless_it_is_renewed() -> None:
    tick = Tick()
    presence = Presence(ttl_s=60, clock=tick)
    holder = object()
    presence.publish(claims(), draft(), holder, NOW)
    tick.now = 59
    assert len(presence.sessions("t_1", NOW)) == 1
    presence.publish(claims(), draft(status=SessionStatus.RUNNING), holder, NOW)
    tick.now = 100
    (card,) = presence.sessions("t_1", NOW)
    assert card.status is SessionStatus.RUNNING
    tick.now = 200
    assert presence.sessions("t_1", NOW) == ()


def test_a_card_disappears_when_its_connection_does() -> None:
    presence = Presence()
    gone, kept = object(), object()
    presence.publish(claims(), draft("r_1"), gone, NOW)
    presence.publish(claims(member="m_b", name="bek"), draft("r_2"), kept, NOW)
    presence.drop_held_by(gone)
    assert [card.room for card in presence.sessions("t_1", NOW)] == ["r_2"]


def test_nobody_can_take_over_someone_elses_room_or_another_teams_view() -> None:
    presence = Presence()
    assert presence.publish(claims(), draft("r_1"), object(), NOW)
    assert not presence.publish(claims(member="m_b", name="bek"), draft("r_1"), object(), NOW)
    assert presence.publish(
        claims(team="t_2", member="m_c", name="cleo"), draft("r_9"), object(), NOW
    )
    assert [card.owner for card in presence.sessions("t_1", NOW)] == ["alia"]
    assert [card.owner for card in presence.sessions("t_2", NOW)] == ["cleo"]


def test_one_member_can_show_only_so_many_sessions() -> None:
    presence = Presence(max_per_member=2)
    assert presence.publish(claims(), draft("r_1"), object(), NOW)
    assert presence.publish(claims(), draft("r_2"), object(), NOW)
    assert not presence.publish(claims(), draft("r_3"), object(), NOW)
    assert presence.publish(claims(), draft("r_2", SessionStatus.RUNNING), object(), NOW)


def test_removing_a_member_or_a_team_clears_their_cards() -> None:
    presence = Presence()
    presence.publish(claims(), draft("r_1"), object(), NOW)
    presence.publish(claims(member="m_b", name="bek"), draft("r_2"), object(), NOW)
    presence.forget_member("t_1", "m_a")
    assert [card.owner for card in presence.sessions("t_1", NOW)] == ["bek"]
    presence.forget_team("t_1")
    assert presence.sessions("t_1", NOW) == ()


def test_the_cards_are_listed_by_owner() -> None:
    presence = Presence()
    presence.publish(claims(member="m_b", name="Bek"), draft("r_2"), object(), NOW)
    presence.publish(claims(), draft("r_1"), object(), NOW)
    assert [card.owner for card in presence.sessions("t_1", NOW)] == ["alia", "Bek"]


def test_the_repository_is_named_from_its_remote() -> None:
    assert name_from_remote("git@github.com:Plural-Organization/Plural.git") == "Plural"
    assert name_from_remote("https://github.com/Plural-Organization/Plural.git") == "Plural"
    assert name_from_remote("https://github.com/org/repo/") == "repo"
    assert name_from_remote("/srv/git/plural") == "plural"
    assert name_from_remote("") is None


def test_status_and_viewers_come_from_the_state() -> None:
    from plural.host.team_presence import status_of, viewers_of

    state = SessionState()
    assert status_of(state) is SessionStatus.IDLE
    people = {
        "p_a": Participant(id="p_a", name="a", role=Role.VIEWER, connected=True),
        "p_b": Participant(id="p_b", name="b", role=Role.VIEWER, connected=False),
        "p_c": Participant(id="p_c", name="c", role=Role.PARTICIPANT, connected=True),
    }
    assert viewers_of(state.model_copy(update={"participants": people})) == 1
    knocking = {"j_1": JoinRequestView(id="j_1", name="x", client="tui", requested_at=NOW)}
    assert status_of(state.model_copy(update={"join_requests": knocking})) is SessionStatus.WAITING


def test_a_team_session_needs_a_team_and_an_address(tmp_path: Path) -> None:
    import pytest

    from plural.host.config import HostSettings
    from plural.host.team import TeamProfile, TeamStore
    from plural.host.team_presence import PresenceUnavailable, ensure_ready
    from plural.protocol.team import MemberView

    store = TeamStore(tmp_path)
    reachable = HostSettings(workspace=tmp_path, data_dir=tmp_path, relay_url="wss://r.example")
    with pytest.raises(PresenceUnavailable, match="not in a team"):
        ensure_ready(reachable, store)
    store.save(
        TeamProfile(
            relay="wss://r.example",
            team_id="t_1",
            team_name="Backend",
            team_key="k",
            certificate="c",
            member=MemberView(id="m_a", name="alia", key="k", role=TeamRole.MEMBER, joined_at=NOW),
        )
    )
    ensure_ready(reachable, store)
    with pytest.raises(PresenceUnavailable, match="reachable"):
        ensure_ready(HostSettings(workspace=tmp_path, data_dir=tmp_path), store)
