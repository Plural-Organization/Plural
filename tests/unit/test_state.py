from datetime import UTC, datetime

from plural.core.provenance import direct
from plural.core.state import OUTPUT_PREVIEW_CHARS, reduce
from plural.protocol.events import (
    Event,
    EventRecord,
    ParticipantJoined,
    ParticipantLeft,
    ParticipantRevoked,
    ProposalApproved,
    ProposalCreated,
    RunEnded,
    RunStarted,
    ToolEnded,
    ToolStarted,
)
from plural.protocol.models import (
    Delivery,
    Participant,
    ProposalView,
    Role,
    RunEndReason,
    SessionState,
    ToolCallView,
    ToolRisk,
)

TS = datetime(2026, 10, 22, tzinfo=UTC)


def fold(*events: Event) -> SessionState:
    state = SessionState()
    for seq, event in enumerate(events, 1):
        state = reduce(state, EventRecord(seq=seq, id=f"e{seq}", ts=TS, actor_id=None, event=event))
    return state


def test_participants_lifecycle() -> None:
    alia = Participant(id="p_alia", name="Alia", role=Role.PARTICIPANT, connected=True)
    state = fold(ParticipantJoined(participant=alia), ParticipantLeft(participant_id="p_alia"))
    assert state.participants["p_alia"].connected is False
    assert state.last_seq == 2
    assert (
        "p_alia"
        not in fold(
            ParticipantJoined(participant=alia), ParticipantRevoked(participant_id="p_alia")
        ).participants
    )


def test_proposal_is_removed_after_decision() -> None:
    proposal = ProposalView(id="pr_1", author_id="p_alia", text="fix", delivery=Delivery.NOW)
    state = fold(
        ProposalCreated(proposal=proposal),
        ProposalApproved(proposal_id="pr_1", decided_by="p_host", text="fix"),
    )
    assert state.proposals == {}


def test_run_and_tool_entries() -> None:
    call = ToolCallView(id="c1", name="bash", risk=ToolRisk.EXEC, subject="pytest")
    state = fold(
        RunStarted(run_id="run_1", prompt_id="pm_1", provenance=direct("p_host", Role.HOST)),
        ToolStarted(run_id="run_1", call=call),
        ToolEnded(run_id="run_1", call_id="c1", ok=True, output="ok"),
    )
    assert state.run is not None
    assert state.transcript[-1].ok is True
    assert fold(RunEnded(run_id="run_1", reason=RunEndReason.STOP)).run is None


def test_tool_output_is_kept_as_a_bounded_preview() -> None:
    call = ToolCallView(id="c1", name="bash", risk=ToolRisk.EXEC, subject="yes")
    state = fold(
        ToolStarted(run_id="run_1", call=call),
        ToolEnded(run_id="run_1", call_id="c1", ok=True, output="x" * (OUTPUT_PREVIEW_CHARS * 3)),
    )
    assert state.transcript[-1].output == "x" * OUTPUT_PREVIEW_CHARS
