from datetime import UTC, datetime, timedelta

import pytest

from plural.core import access, visibility
from plural.core.errors import Conflict, NotFound
from plural.core.roles import can
from plural.core.state import reduce
from plural.protocol.commands import AccessDecide, AccessRequest, PromptSubmit
from plural.protocol.events import (
    AccessRequested,
    AccessResolved,
    Event,
    EventRecord,
    ParticipantRevoked,
    ParticipantRoleChanged,
)
from plural.protocol.models import (
    HOST_PARTICIPANT_ID,
    AccessDecision,
    Participant,
    Role,
    SessionState,
)

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
CLEO = Participant(id="p_cleo", name="Cleo", role=Role.VIEWER, connected=True)
BEK = Participant(id="p_bek", name="Bek", role=Role.VIEWER, connected=True)
ALIA = Participant(id="p_alia", name="Alia", role=Role.PARTICIPANT, connected=True)


def record(seq: int, event: Event) -> EventRecord:
    return EventRecord(seq=seq, id=f"e{seq}", ts=NOW, actor_id=None, event=event)


def ask(
    state: SessionState,
    who: Participant = CLEO,
    note: str | None = None,
    *,
    now: datetime = NOW,
    limit: int = 5,
    denied: dict[str, datetime] | None = None,
) -> AccessRequested:
    return access.request(state, who, note, now=now, limit=limit, denied_at=denied or {})


def asking(*people: Participant) -> SessionState:
    state = SessionState(participants={person.id: person for person in (CLEO, BEK, ALIA)})
    for seq, person in enumerate(people, 1):
        state = reduce(state, record(seq, ask(state, person)))
    return state


def test_a_viewer_can_ask_with_a_note_and_the_request_is_kept() -> None:
    state = SessionState(participants={CLEO.id: CLEO})
    asked = ask(state, note="I can fix the test")
    assert (asked.request.participant_id, asked.request.name, asked.request.note) == (
        "p_cleo",
        "Cleo",
        "I can fix the test",
    )
    assert list(reduce(state, record(1, asked)).access_requests) == ["p_cleo"]


def test_someone_who_can_already_write_has_nothing_to_ask() -> None:
    with pytest.raises(Conflict, match="already write"):
        ask(SessionState(participants={ALIA.id: ALIA}), ALIA)


def test_asking_twice_is_refused_while_the_first_waits() -> None:
    with pytest.raises(Conflict, match="already asked"):
        ask(asking(CLEO))


def test_only_so_many_may_wait_at_once() -> None:
    with pytest.raises(Conflict, match="too many"):
        ask(asking(BEK), limit=1)


def test_after_a_refusal_the_person_waits_before_asking_again() -> None:
    state = SessionState(participants={CLEO.id: CLEO})
    denied = {CLEO.id: NOW}
    with pytest.raises(Conflict, match="said no"):
        ask(state, now=NOW + timedelta(minutes=4), denied=denied)
    assert ask(state, now=NOW + timedelta(minutes=6), denied=denied)


def test_allowing_resolves_the_request_and_makes_the_viewer_a_participant() -> None:
    state = asking(CLEO)
    events = access.decide(state, "p_cleo", True, HOST_PARTICIPANT_ID)
    assert [type(event) for event in events] == [AccessResolved, ParticipantRoleChanged]
    resolved, changed = events
    assert isinstance(resolved, AccessResolved)
    assert resolved.decision is AccessDecision.GRANTED
    assert isinstance(changed, ParticipantRoleChanged)
    assert changed.role is Role.PARTICIPANT
    for seq, event in enumerate(events, 10):
        state = reduce(state, record(seq, event))
    assert state.access_requests == {}
    assert state.participants["p_cleo"].role is Role.PARTICIPANT


def test_denying_only_resolves_the_request() -> None:
    state = asking(CLEO)
    (resolved,) = access.decide(state, "p_cleo", False, HOST_PARTICIPANT_ID)
    assert isinstance(resolved, AccessResolved)
    assert resolved.decision is AccessDecision.DENIED
    state = reduce(state, record(9, resolved))
    assert state.access_requests == {}
    assert state.participants["p_cleo"].role is Role.VIEWER


def test_answering_a_request_that_is_not_there_is_not_found() -> None:
    with pytest.raises(NotFound):
        access.decide(SessionState(), "p_cleo", True, HOST_PARTICIPANT_ID)


def test_a_role_change_or_a_removal_drops_a_waiting_request() -> None:
    state = asking(CLEO, BEK)
    state = reduce(
        state, record(8, ParticipantRoleChanged(participant_id="p_cleo", role=Role.PARTICIPANT))
    )
    state = reduce(state, record(9, ParticipantRevoked(participant_id="p_bek")))
    assert state.access_requests == {}


def test_only_the_host_and_the_asker_see_a_request_and_its_answer() -> None:
    asked = ask(SessionState(participants={BEK.id: BEK}), BEK)
    answer = AccessResolved(participant_id="p_cleo", decision=AccessDecision.DENIED)
    for event, who, expected in [
        (asked, HOST_PARTICIPANT_ID, True),
        (asked, "p_bek", True),
        (asked, "p_cleo", False),
        (answer, HOST_PARTICIPANT_ID, True),
        (answer, "p_cleo", True),
        (answer, "p_bek", False),
    ]:
        assert visibility.visible_to(event, who) is expected


def test_a_snapshot_shows_a_person_only_their_own_request() -> None:
    state = asking(CLEO, BEK)
    assert set(visibility.state_for(state, HOST_PARTICIPANT_ID).access_requests) == {
        "p_cleo",
        "p_bek",
    }
    assert set(visibility.state_for(state, "p_cleo").access_requests) == {"p_cleo"}
    assert visibility.state_for(state, "p_alia").access_requests == {}


def test_who_may_ask_and_who_may_answer() -> None:
    assert all(can(role, AccessRequest()) for role in Role)
    assert can(Role.HOST, AccessDecide(participant_id="p", decision="allow"))
    assert not can(Role.PARTICIPANT, AccessDecide(participant_id="p", decision="allow"))
    assert not can(Role.VIEWER, AccessDecide(participant_id="p", decision="allow"))
    assert not can(Role.VIEWER, PromptSubmit(text="x"))
