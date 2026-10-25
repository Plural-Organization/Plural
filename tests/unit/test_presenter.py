from datetime import UTC, datetime

from plural.client.presenter import Line, describe, history, label, live
from plural.client.projection import Projection
from plural.core.provenance import direct
from plural.protocol.events import (
    ContextCompacted,
    EventRecord,
    MessageDelta,
    MessageEnded,
    PolicyRuleAdded,
    PolicyRuleRemoved,
    RunEnded,
)
from plural.protocol.models import (
    ApprovalView,
    EntryKind,
    Participant,
    PolicyAction,
    PolicyRuleView,
    Role,
    RunView,
    SessionState,
    ToolCallView,
    ToolRisk,
    TranscriptEntry,
)


def test_history_renders_transcript_for_late_joiners() -> None:
    call = ToolCallView(id="c1", name="bash", risk=ToolRisk.EXEC, subject="cat notes.txt")
    state = SessionState(
        participants={"p_alia": Participant(id="p_alia", name="Alia", role=Role.PARTICIPANT)},
        transcript=(
            TranscriptEntry(id="pm1", kind=EntryKind.PROMPT, author_id="p_alia", text="$ ls"),
            TranscriptEntry(id="m1", kind=EntryKind.ASSISTANT, text=""),
            TranscriptEntry(id="c1", kind=EntryKind.TOOL, tool=call, ok=True),
            TranscriptEntry(id="m2", kind=EntryKind.ASSISTANT, text="done"),
        ),
    )
    assert history(state) == [
        Line("bold", "Alia › $ ls"),
        Line("cyan", "⚙ bash cat notes.txt ✓"),
        Line("", "done"),
    ]


def test_history_keeps_tool_output_preview() -> None:
    call = ToolCallView(id="c1", name="bash", risk=ToolRisk.EXEC, subject="false")
    state = SessionState(
        transcript=(
            TranscriptEntry(id="c1", kind=EntryKind.TOOL, tool=call, ok=False, output="boom"),
        )
    )
    assert history(state) == [Line("red", "⚙ bash false ✗"), Line("red", "boom")]


def test_same_names_get_a_suffix() -> None:
    bek = Participant(id="p_01ABCDWXYZ", name="Bek", role=Role.PARTICIPANT)
    other = Participant(id="p_01ABCDQRST", name="Bek", role=Role.PARTICIPANT)
    alia = Participant(id="p_alia", name="Alia", role=Role.PARTICIPANT)
    state = SessionState(participants={p.id: p for p in (bek, other, alia)})
    assert label(state, alia) == "Alia"
    assert label(state, bek) == "Bek #WXYZ"
    assert label(state, other) == "Bek #QRST"


def record(seq: int, event: MessageEnded | RunEnded) -> EventRecord:
    return EventRecord(
        seq=seq, id=f"e{seq}", ts=datetime(2026, 10, 25, tzinfo=UTC), actor_id=None, event=event
    )


def test_live_status_follows_the_run() -> None:
    projection = Projection()
    assert live(projection) == ""

    projection.state = SessionState(
        run=RunView(id="run_1", prompt_id="pm_1", provenance=direct("p_host", Role.HOST))
    )
    assert live(projection) == "… waiting for the model"

    projection.observe(MessageDelta(message_id="m1", text="hmm", thinking=True))
    assert live(projection) == "… thinking (3 chars)"

    projection.observe(MessageDelta(message_id="m1", text="Hello"))
    assert live(projection) == "Hello"

    projection.apply(record(1, MessageEnded(run_id="run_1", message_id="m1", text="Hello")))
    assert projection.reasoning == 0
    assert live(projection) == "… waiting for the model"

    call = ToolCallView(id="c1", name="bash", risk=ToolRisk.EXEC, subject="ls")
    projection.state = projection.state.model_copy(
        update={"transcript": (TranscriptEntry(id="c1", kind=EntryKind.TOOL, tool=call),)}
    )
    assert live(projection) == "… running bash"

    approval = ApprovalView(
        id="a1",
        call=call,
        provenance=direct("p_host", Role.HOST),
        timeout_at=datetime(2026, 10, 25, tzinfo=UTC),
    )
    projection.state = projection.state.model_copy(update={"approvals": {"a1": approval}})
    assert live(projection) == "… waiting for host approval"


def test_policy_changes_are_described() -> None:
    rule = PolicyRuleView(id="pl_1", tool="bash", pattern="make *", action=PolicyAction.ALLOW)
    state = SessionState()
    assert describe(PolicyRuleAdded(rule=rule), state) == Line(
        "magenta", "policy + allow bash make *  [pl_1]"
    )
    assert describe(PolicyRuleRemoved(rule_id="pl_1"), state) == Line("magenta", "policy - pl_1")


def test_compaction_is_shown_in_history_and_live() -> None:
    state = SessionState(
        transcript=(
            TranscriptEntry(
                id="e1", kind=EntryKind.COMPACTION, text="context compacted (900 tokens summarized)"
            ),
        )
    )
    assert history(state) == [Line("dim", "⟲ context compacted (900 tokens summarized)")]
    event = ContextCompacted(run_id="run_1", summary="s", tokens_before=900)
    assert describe(event, SessionState()) == history(state)[0]
