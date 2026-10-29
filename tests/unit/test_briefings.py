from datetime import UTC, datetime, timedelta

import pytest

from plural.core import briefings, visibility
from plural.core.errors import Conflict, NotFound
from plural.core.roles import can
from plural.core.state import reduce
from plural.protocol.commands import (
    BriefingDecide,
    BriefingImport,
    BriefingRequest,
    BriefingSharingSet,
)
from plural.protocol.events import (
    BriefingDelivered,
    BriefingImported,
    BriefingRequested,
    BriefingResolved,
    BriefingSharingChanged,
    Event,
    EventRecord,
    ParticipantLeft,
    ParticipantRevoked,
)
from plural.protocol.models import (
    HOST_PARTICIPANT_ID,
    BriefingDecision,
    BriefingImportView,
    BriefingSharing,
    Participant,
    Role,
    SessionState,
)

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
ALIA = Participant(id="p_alia", name="Alia", role=Role.PARTICIPANT, connected=True)
CLEO = Participant(id="p_cleo", name="Cleo", role=Role.VIEWER, connected=True)


def record(seq: int, event: Event) -> EventRecord:
    return EventRecord(seq=seq, id=f"e{seq}", ts=NOW, actor_id=None, event=event)


def state(sharing: BriefingSharing = BriefingSharing.ASK) -> SessionState:
    return SessionState(briefing_sharing=sharing, participants={ALIA.id: ALIA, CLEO.id: CLEO})


def ask(
    current: SessionState,
    who: Participant = CLEO,
    *,
    focus: str | None = None,
    update: bool = False,
    request_id: str = "b_1",
    now: datetime = NOW,
    limit: int = 5,
    last: dict[str, datetime] | None = None,
) -> BriefingRequested:
    return briefings.request(
        current,
        who,
        focus,
        update,
        request_id=request_id,
        now=now,
        limit=limit,
        last_at=last or {},
    )


def test_a_request_keeps_who_asked_what_and_whether_it_is_an_update() -> None:
    asked = ask(state(), focus="how was login fixed", update=True)
    assert (asked.request.participant_id, asked.request.focus, asked.request.update) == (
        "p_cleo",
        "how was login fixed",
        True,
    )
    assert list(reduce(state(), record(1, asked)).briefing_requests) == ["b_1"]


def test_a_session_that_shares_nothing_refuses() -> None:
    with pytest.raises(Conflict, match="does not share"):
        ask(state(BriefingSharing.OFF))


def test_one_request_at_a_time_per_person_and_a_limit_on_the_queue() -> None:
    waiting = reduce(state(), record(1, ask(state())))
    with pytest.raises(Conflict, match="already asked"):
        ask(waiting, request_id="b_2")
    with pytest.raises(Conflict, match="too many"):
        ask(waiting, ALIA, request_id="b_2", limit=1)


def test_a_person_waits_a_minute_between_briefings() -> None:
    last = {CLEO.id: NOW}
    with pytest.raises(Conflict, match="a minute"):
        ask(state(), now=NOW + timedelta(seconds=30), last=last)
    assert ask(state(), now=NOW + timedelta(seconds=61), last=last)


def test_answering_resolves_the_request() -> None:
    waiting = reduce(state(), record(1, ask(state())))
    granted = briefings.decide(waiting, "b_1", True, HOST_PARTICIPANT_ID)
    assert granted.decision is BriefingDecision.GRANTED
    assert granted.participant_id == "p_cleo"
    denied = briefings.decide(waiting, "b_1", False, HOST_PARTICIPANT_ID)
    assert denied.decision is BriefingDecision.DENIED
    assert reduce(waiting, record(2, granted)).briefing_requests == {}
    with pytest.raises(NotFound):
        briefings.decide(state(), "b_1", True, HOST_PARTICIPANT_ID)


def test_a_request_goes_when_the_person_leaves_or_is_removed() -> None:
    waiting = reduce(state(), record(1, ask(state())))
    assert (
        reduce(waiting, record(2, ParticipantLeft(participant_id="p_cleo"))).briefing_requests == {}
    )
    assert (
        reduce(waiting, record(2, ParticipantRevoked(participant_id="p_cleo"))).briefing_requests
        == {}
    )
    assert (
        len(reduce(waiting, record(2, ParticipantLeft(participant_id="p_alia"))).briefing_requests)
        == 1
    )


def test_the_sharing_mode_and_what_was_given_to_the_agent_are_kept() -> None:
    current = reduce(state(), record(1, BriefingSharingChanged(mode=BriefingSharing.TEAM)))
    assert current.briefing_sharing is BriefingSharing.TEAM
    for index in range(12):
        item = BriefingImportView(id=f"bi_{index}", source="alia", as_of_seq=index, chars=5, at=NOW)
        current = reduce(current, record(10 + index, BriefingImported(item=item, text="notes")))
    assert [item.id for item in current.briefings_imported] == [f"bi_{n}" for n in range(2, 12)]


def test_only_the_host_and_the_asker_see_a_request_its_answer_and_the_briefing() -> None:
    asked = ask(state())
    answer = BriefingResolved(
        request_id="b_1", participant_id="p_cleo", decision=BriefingDecision.GRANTED
    )
    delivered = BriefingDelivered(request_id="b_1", to="p_cleo", text="secret plans", as_of_seq=3)
    for event in (asked, answer, delivered):
        assert visibility.visible_to(event, HOST_PARTICIPANT_ID)
        assert visibility.visible_to(event, "p_cleo")
        assert not visibility.visible_to(event, "p_alia")


def test_a_snapshot_shows_a_person_only_their_own_request() -> None:
    both = reduce(
        reduce(state(), record(1, ask(state()))), record(2, ask(state(), ALIA, request_id="b_2"))
    )
    assert set(visibility.state_for(both, HOST_PARTICIPANT_ID).briefing_requests) == {"b_1", "b_2"}
    assert set(visibility.state_for(both, "p_cleo").briefing_requests) == {"b_1"}
    assert visibility.state_for(both, "p_other").briefing_requests == {}


def test_who_may_ask_who_answers_and_who_gives_notes_to_an_agent() -> None:
    assert can(Role.VIEWER, BriefingRequest())
    assert can(Role.PARTICIPANT, BriefingRequest())
    assert not can(Role.HOST, BriefingRequest())
    for command in (
        BriefingDecide(request_id="b", decision="allow"),
        BriefingSharingSet(mode=BriefingSharing.OFF),
        BriefingImport(source="alia", text="notes"),
    ):
        assert can(Role.HOST, command)
        assert not can(Role.PARTICIPANT, command)
        assert not can(Role.VIEWER, command)
