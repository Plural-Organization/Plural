from datetime import UTC, datetime, timedelta

import pytest

from plural.core import approvals
from plural.core.errors import Forbidden, NotFound
from plural.core.roles import can
from plural.core.state import reduce
from plural.protocol.commands import ApprovalRespond, ApproverSet
from plural.protocol.events import (
    ApproverChanged,
    EventRecord,
    ParticipantJoined,
    ParticipantRevoked,
    ParticipantRoleChanged,
)
from plural.protocol.models import (
    HOST_PARTICIPANT_ID,
    ApprovalDecision,
    ApprovalView,
    FolderAccess,
    Origin,
    Participant,
    Provenance,
    Role,
    SessionState,
    ToolCallView,
    ToolRisk,
)

TS = datetime(2026, 11, 26, tzinfo=UTC)
HOST = Participant(id=HOST_PARTICIPANT_ID, name="Host", role=Role.HOST, connected=True)
ALIA = Participant(id="p_alia", name="Alia", role=Role.PARTICIPANT, connected=True)
BEK = Participant(id="p_bek", name="Bek", role=Role.PARTICIPANT, connected=True)
VIEW = Participant(id="p_view", name="Cleo", role=Role.VIEWER, connected=True)


def call() -> ToolCallView:
    return ToolCallView(id="c1", name="bash", subject="make test", risk=ToolRisk.EXEC)


def approval(initiator: Participant, *, folder: FolderAccess | None = None) -> ApprovalView:
    return ApprovalView(
        id="ap_1",
        call=call(),
        provenance=Provenance(
            initiator_id=initiator.id, initiator_role=initiator.role, origin=Origin.DIRECT
        ),
        timeout_at=TS + timedelta(minutes=5),
        folder=folder,
    )


def room(*approvers: str, asking: ApprovalView | None = None) -> SessionState:
    people = {person.id: person for person in (HOST, ALIA, BEK, VIEW)}
    return SessionState(
        participants=people,
        approvers=approvers,
        approvals={asking.id: asking} if asking else {},
    )


def answer(state: SessionState, who: Participant, decision: ApprovalDecision) -> None:
    approvals.authorize_response(state, approval_id="ap_1", decision=decision, responder=who)


def test_the_host_answers_everything() -> None:
    state = room(asking=approval(ALIA))
    for decision in (ApprovalDecision.ONCE, ApprovalDecision.ALWAYS, ApprovalDecision.BLOCK):
        answer(state, HOST, decision)


def test_a_named_approver_answers_once_or_reject_for_someone_else() -> None:
    state = room(BEK.id, asking=approval(ALIA))
    answer(state, BEK, ApprovalDecision.ONCE)
    answer(state, BEK, ApprovalDecision.REJECT)


@pytest.mark.parametrize("decision", [ApprovalDecision.ALWAYS, ApprovalDecision.BLOCK])
def test_an_approver_cannot_make_a_rule(decision: ApprovalDecision) -> None:
    state = room(BEK.id, asking=approval(ALIA))
    with pytest.raises(Forbidden):
        answer(state, BEK, decision)


def test_an_approver_cannot_approve_their_own_prompt() -> None:
    state = room(BEK.id, asking=approval(BEK))
    with pytest.raises(Forbidden, match="your own"):
        answer(state, BEK, ApprovalDecision.ONCE)


def test_an_approver_does_not_open_a_folder() -> None:
    folder = FolderAccess(folder="/etc", write=False)
    state = room(BEK.id, asking=approval(ALIA, folder=folder))
    for decision in (ApprovalDecision.ONCE, ApprovalDecision.READ, ApprovalDecision.REJECT):
        with pytest.raises(Forbidden, match="folder"):
            answer(state, BEK, decision)


def test_someone_who_was_not_named_cannot_answer() -> None:
    state = room(BEK.id, asking=approval(ALIA))
    with pytest.raises(Forbidden):
        answer(state, ALIA, ApprovalDecision.ONCE)
    with pytest.raises(Forbidden):
        answer(state, VIEW, ApprovalDecision.ONCE)


def test_a_viewer_stays_out_even_when_their_id_is_in_the_list() -> None:
    state = room(VIEW.id, asking=approval(ALIA))
    with pytest.raises(Forbidden):
        answer(state, VIEW, ApprovalDecision.ONCE)


def test_an_unknown_approval_is_not_found_for_a_guest() -> None:
    with pytest.raises(NotFound):
        answer(room(BEK.id), BEK, ApprovalDecision.ONCE)


def test_the_matrix_lets_participants_send_the_answer_but_only_the_host_names_approvers() -> None:
    respond = ApprovalRespond(approval_id="ap_1", decision=ApprovalDecision.ONCE)
    name = ApproverSet(participant_id=BEK.id, enabled=True)
    assert can(Role.HOST, respond)
    assert can(Role.PARTICIPANT, respond)
    assert not can(Role.VIEWER, respond)
    assert can(Role.HOST, name)
    assert not can(Role.PARTICIPANT, name)
    assert not can(Role.VIEWER, name)


def fold(state: SessionState, *events: object) -> SessionState:
    for seq, event in enumerate(events, 1):
        record = EventRecord(seq=seq, id=f"e{seq}", ts=TS, actor_id=None, event=event)  # type: ignore[arg-type]
        state = reduce(state, record)
    return state


def test_the_reducer_adds_and_removes_an_approver_once() -> None:
    named = fold(room(), ApproverChanged(participant_id=BEK.id, enabled=True))
    assert named.approvers == (BEK.id,)
    again = fold(named, ApproverChanged(participant_id=BEK.id, enabled=True))
    assert again.approvers == (BEK.id,)
    off = fold(again, ApproverChanged(participant_id=BEK.id, enabled=False))
    assert off.approvers == ()


def test_losing_the_right_to_write_or_the_seat_ends_the_approval_right() -> None:
    named = room(BEK.id, ALIA.id)
    demoted = fold(named, ParticipantRoleChanged(participant_id=BEK.id, role=Role.VIEWER))
    assert demoted.approvers == (ALIA.id,)
    kicked = fold(named, ParticipantRevoked(participant_id=ALIA.id))
    assert kicked.approvers == (BEK.id,)
    kept = fold(named, ParticipantRoleChanged(participant_id=BEK.id, role=Role.PARTICIPANT))
    assert kept.approvers == (BEK.id, ALIA.id)


def test_joining_does_not_make_anyone_an_approver() -> None:
    joined = fold(SessionState(), ParticipantJoined(participant=BEK))
    assert joined.approvers == ()
