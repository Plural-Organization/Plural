from datetime import UTC, datetime

import pytest

from plural.core import handover
from plural.core.errors import Conflict, Forbidden, Invalid, NotFound
from plural.core.state import reduce
from plural.protocol.events import (
    EventRecord,
    HostHandedOver,
    HostHandoverAccepted,
    HostHandoverEnded,
    HostHandoverOffered,
)
from plural.protocol.models import (
    HOST_PARTICIPANT_ID,
    BoardStroke,
    BoardView,
    ChatEntry,
    EntryKind,
    HandoverEnd,
    Participant,
    Role,
    SessionState,
    TranscriptEntry,
)

TS = datetime(2026, 11, 26, tzinfo=UTC)
BOB = Participant(id=HOST_PARTICIPANT_ID, name="Bob", role=Role.HOST, connected=True)
ALIA = Participant(id="p_alia", name="Alia", role=Role.PARTICIPANT, connected=True)
CLEO = Participant(id="p_cleo", name="Cleo", role=Role.PARTICIPANT, connected=True)
DEE = Participant(id="p_dee", name="Dee", role=Role.VIEWER, connected=True)
AWAY = Participant(id="p_away", name="Eli", role=Role.PARTICIPANT, connected=False)


def room(**over: object) -> SessionState:
    people = {person.id: person for person in (BOB, ALIA, CLEO, DEE, AWAY)}
    return SessionState(participants=people, **over)  # type: ignore[arg-type]


def apply(state: SessionState, *events: object) -> SessionState:
    for seq, event in enumerate(events, 1):
        state = reduce(
            state,
            EventRecord(seq=seq, id=f"e{seq}", ts=TS, actor_id=None, event=event),  # type: ignore[arg-type]
        )
    return state


def test_the_host_offers_to_a_participant_who_is_here() -> None:
    offered = handover.offer(room(), participant_id=ALIA.id)
    assert (offered.participant_id, offered.name) == (ALIA.id, "Alia")
    state = apply(room(), offered)
    assert state.handover is not None
    assert state.handover.participant_id == ALIA.id
    assert not state.handover.accepted


@pytest.mark.parametrize(
    ("who", "error"),
    [("p_nobody", NotFound), (DEE.id, Invalid), (AWAY.id, Invalid), (BOB.id, Invalid)],
)
def test_an_offer_needs_a_participant_who_can_write_and_is_connected(
    who: str, error: type[Exception]
) -> None:
    with pytest.raises(error):
        handover.offer(room(), participant_id=who)


def test_only_one_offer_stands_at_a_time() -> None:
    state = apply(room(), HostHandoverOffered(participant_id=ALIA.id, name="Alia"))
    with pytest.raises(Conflict, match="already"):
        handover.offer(state, participant_id=CLEO.id)


def test_only_the_one_offered_accepts_and_only_once() -> None:
    state = apply(room(), HostHandoverOffered(participant_id=ALIA.id, name="Alia"))
    with pytest.raises(Forbidden):
        handover.accept(state, CLEO)
    with pytest.raises(Conflict):
        handover.accept(room(), ALIA)
    accepted = handover.accept(state, ALIA)
    assert accepted == HostHandoverAccepted(participant_id=ALIA.id)
    state = apply(state, accepted)
    assert state.handover is not None
    assert state.handover.accepted
    with pytest.raises(Conflict, match="already"):
        handover.accept(state, ALIA)


def test_an_ended_offer_is_gone_and_nothing_ends_when_there_is_none() -> None:
    state = apply(room(), HostHandoverOffered(participant_id=ALIA.id, name="Alia"))
    ended = handover.end(state, HandoverEnd.DECLINED)
    assert ended == HostHandoverEnded(reason=HandoverEnd.DECLINED)
    assert apply(state, ended).handover is None
    assert handover.end(room(), HandoverEnd.DECLINED) is None


def stroke(by: str) -> BoardStroke:
    return BoardStroke(
        id=f"s_{by}", author_id=by, color="#000000", width=2, points=(0.0, 0.0, 1.0, 1.0)
    )  # type: ignore[arg-type]


def history() -> SessionState:
    return room(
        approvers=(ALIA.id, CLEO.id),
        transcript=(
            TranscriptEntry(id="t1", kind=EntryKind.PROMPT, author_id=BOB.id, text="by Bob"),
            TranscriptEntry(id="t2", kind=EntryKind.PROMPT, author_id=ALIA.id, text="by Alia"),
            TranscriptEntry(id="t3", kind=EntryKind.PROMPT, author_id=CLEO.id, text="by Cleo"),
            TranscriptEntry(id="t4", kind=EntryKind.ASSISTANT, text="an answer"),
        ),
        chat=(
            ChatEntry(
                id="c1", author_id=BOB.id, text="hi @alia", ts=TS, to=ALIA.id, mentions=(ALIA.id,)
            ),
            ChatEntry(id="c2", author_id=ALIA.id, text="hi Bob", ts=TS, to=BOB.id),
        ),
        board=BoardView(open=True, strokes=(stroke(BOB.id), stroke(ALIA.id))),
    )


def test_the_seat_moves_and_what_each_wrote_stays_theirs() -> None:
    state = apply(
        history(),
        HostHandedOver(
            former_host_id="p_bob_now", former_host_name="Bob", participant_id=ALIA.id, name="Alia"
        ),
    )
    host = state.participants[HOST_PARTICIPANT_ID]
    assert (host.name, host.role) == ("Alia", Role.HOST)
    former = state.participants["p_bob_now"]
    assert (former.name, former.role) == ("Bob", Role.PARTICIPANT)
    assert ALIA.id not in state.participants
    assert state.handovers == 1
    assert state.handover is None
    # Bob's words are Bob's, under his new id; what Alia said as a participant is the host's now.
    assert [(e.id, e.author_id) for e in state.transcript] == [
        ("t1", "p_bob_now"),
        ("t2", HOST_PARTICIPANT_ID),
        ("t3", CLEO.id),
        ("t4", None),
    ]
    first, second = state.chat
    assert (first.author_id, first.to, first.mentions) == (
        "p_bob_now",
        HOST_PARTICIPANT_ID,
        (HOST_PARTICIPANT_ID,),
    )
    assert (second.author_id, second.to) == (HOST_PARTICIPANT_ID, "p_bob_now")
    assert [s.author_id for s in state.board.strokes] == ["p_bob_now", HOST_PARTICIPANT_ID]
    # The seat is not an approver: the host answers for itself, and Alia's right went with her id.
    assert state.approvers == (CLEO.id,)


def test_the_new_host_is_not_shown_as_connected_before_it_is() -> None:
    state = apply(
        history(),
        HostHandedOver(
            former_host_id="p_bob_now", former_host_name="Bob", participant_id=ALIA.id, name="Alia"
        ),
    )
    assert not state.participants[HOST_PARTICIPANT_ID].connected
    assert not state.participants["p_bob_now"].connected


def test_a_second_handover_passes_the_seat_on_again() -> None:
    first = HostHandedOver(
        former_host_id="p_bob_now", former_host_name="Bob", participant_id=ALIA.id, name="Alia"
    )
    second = HostHandedOver(
        former_host_id="p_alia_now", former_host_name="Alia", participant_id=CLEO.id, name="Cleo"
    )
    state = apply(history(), first, second)
    assert state.handovers == 2
    assert state.participants[HOST_PARTICIPANT_ID].name == "Cleo"
    owners = {e.id: e.author_id for e in state.transcript}
    assert owners["t1"] == "p_bob_now"
    assert owners["t2"] == "p_alia_now"
    assert owners["t3"] == HOST_PARTICIPANT_ID
