from datetime import UTC, datetime

from plural.agent.messages import AssistantTurn, SummaryTurn, ToolResultTurn, UserTurn
from plural.core.provenance import direct
from plural.host.history import INTERRUPTED, replay
from plural.protocol.events import (
    ContextCompacted,
    Event,
    EventRecord,
    MessageEnded,
    PromptAccepted,
    PromptDequeued,
    RunEnded,
    RunStarted,
    ToolEnded,
    ToolStarted,
)
from plural.protocol.models import (
    Delivery,
    DequeueReason,
    Role,
    RunEndReason,
    ToolCallView,
    ToolRisk,
)


def records(*events: Event) -> list[EventRecord]:
    now = datetime.now(UTC)
    return [
        EventRecord(seq=seq, id=f"ev_{seq}", ts=now, actor_id=None, event=event)
        for seq, event in enumerate(events, start=1)
    ]


def prompt(prompt_id: str, text: str) -> PromptAccepted:
    return PromptAccepted(
        prompt_id=prompt_id,
        author_id="p_host",
        text=text,
        delivery=Delivery.STEER,
        provenance=direct("p_host", Role.HOST),
    )


def test_a_steered_prompt_and_an_interrupted_call_are_restored() -> None:
    call = ToolCallView(id="c1", name="bash", risk=ToolRisk.EXEC, args={"command": "sleep 9"})
    log = records(
        prompt("pm_1", "start"),
        RunStarted(run_id="run_1", prompt_id="pm_1", provenance=direct("p_host", Role.HOST)),
        prompt("pm_2", "also this"),
        MessageEnded(run_id="run_1", message_id="m1", text=""),
        ToolStarted(run_id="run_1", call=call),
        RunEnded(run_id="run_1", reason=RunEndReason.ERROR, error="host restarted"),
        PromptDequeued(prompt_id="pm_2", reason=DequeueReason.DROPPED),
    )
    conversation = replay(log, names={"p_host": "Vlad"}, texts={})

    assert isinstance(conversation[0], UserTurn)
    assert conversation[0].author.name == "Vlad"
    assert isinstance(conversation[1], AssistantTurn)
    assert conversation[1].tool_calls[0].id == "c1"
    assert conversation[2] == ToolResultTurn(
        call_id="c1", name="bash", content=INTERRUPTED, is_error=True
    )
    assert len(conversation) == 3


def test_compaction_keeps_the_summary_and_the_run_prompt() -> None:
    log = records(
        prompt("pm_1", "start"),
        RunStarted(run_id="run_1", prompt_id="pm_1", provenance=direct("p_host", Role.HOST)),
        MessageEnded(run_id="run_1", message_id="m1", text="working"),
        ContextCompacted(run_id="run_1", summary="notes", tokens_before=900),
        prompt("pm_2", "more"),
        PromptDequeued(prompt_id="pm_2", reason=DequeueReason.DELIVERED),
        MessageEnded(run_id="run_1", message_id="m2", text="done"),
        RunEnded(run_id="run_1", reason=RunEndReason.STOP),
    )
    conversation = replay(log, names={}, texts={"pm_1": "start with attachment"})

    assert conversation[0] == SummaryTurn(text="notes")
    assert isinstance(conversation[1], UserTurn)
    assert conversation[1].text == "start with attachment"
    assert isinstance(conversation[2], UserTurn)
    assert conversation[2].text == "more"
    assert conversation[3] == AssistantTurn(text="done")


def test_results_follow_call_order_and_orphans_are_dropped() -> None:
    first = ToolCallView(id="c1", name="read", risk=ToolRisk.READ, args={"path": "a"})
    second = ToolCallView(id="c2", name="read", risk=ToolRisk.READ, args={"path": "b"})
    log = records(
        prompt("pm_1", "start"),
        RunStarted(run_id="run_1", prompt_id="pm_1", provenance=direct("p_host", Role.HOST)),
        ToolStarted(run_id="run_1", call=ToolCallView(id="c0", name="ls", risk=ToolRisk.READ)),
        ToolEnded(run_id="run_1", call_id="c0", ok=True, output="orphan"),
        MessageEnded(run_id="run_1", message_id="m1", text=""),
        ToolStarted(run_id="run_1", call=first),
        ToolStarted(run_id="run_1", call=second),
        ToolEnded(run_id="run_1", call_id="c2", ok=True, output="bee"),
        ToolEnded(run_id="run_1", call_id="c1", ok=True, output="ay"),
        RunEnded(run_id="run_1", reason=RunEndReason.STOP),
    )
    conversation = replay(log, names={}, texts={})

    results = [m for m in conversation if isinstance(m, ToolResultTurn)]
    assert [r.call_id for r in results] == ["c1", "c2"]
