from collections.abc import Sequence
from datetime import UTC, datetime

from plural.agent.messages import AssistantTurn, NotesTurn, ToolResultTurn, UserTurn
from plural.host.history import replay
from plural.protocol.events import (
    BriefingImported,
    Event,
    EventRecord,
    MessageEnded,
    PromptAccepted,
    RunEnded,
    RunStarted,
    ToolEnded,
    ToolStarted,
)
from plural.protocol.models import (
    BriefingImportView,
    Delivery,
    Origin,
    Provenance,
    Role,
    RunEndReason,
    ToolCallView,
    ToolRisk,
)

NOW = datetime(2026, 10, 29, tzinfo=UTC)
HOST = Provenance(initiator_id="p_host", initiator_role=Role.HOST, origin=Origin.DIRECT)


def records(*events: Event) -> list[EventRecord]:
    return [
        EventRecord(seq=index, id=f"e{index}", ts=NOW, actor_id=None, event=event)
        for index, event in enumerate(events, 1)
    ]


def prompt(prompt_id: str, text: str) -> PromptAccepted:
    return PromptAccepted(
        prompt_id=prompt_id, author_id="p_host", text=text, delivery=Delivery.NOW, provenance=HOST
    )


def imported(source: str, text: str) -> BriefingImported:
    item = BriefingImportView(
        id=f"bi_{source}", source=source, as_of_seq=1, chars=len(text), at=NOW
    )
    return BriefingImported(item=item, text=text)


def kinds(messages: Sequence[object]) -> list[str]:
    return [type(message).__name__ for message in messages]


def test_notes_given_between_runs_sit_where_they_were_given() -> None:
    messages = replay(
        records(
            prompt("p1", "first"),
            RunStarted(run_id="r1", prompt_id="p1", provenance=HOST),
            MessageEnded(run_id="r1", message_id="m1", text="done"),
            RunEnded(run_id="r1", reason=RunEndReason.STOP),
            imported("bek", "notes"),
            prompt("p2", "second"),
            RunStarted(run_id="r2", prompt_id="p2", provenance=HOST),
        ),
        names={"p_host": "vlad"},
        texts={},
    )
    assert kinds(messages) == ["UserTurn", "AssistantTurn", "NotesTurn", "UserTurn"]


def test_notes_given_during_a_run_wait_for_the_next_prompt_instead_of_splitting_a_tool_round() -> (
    None
):
    call = ToolCallView(id="c1", name="ls", risk=ToolRisk.READ, subject=".", args={})
    messages = replay(
        records(
            prompt("p1", "first"),
            RunStarted(run_id="r1", prompt_id="p1", provenance=HOST),
            MessageEnded(run_id="r1", message_id="m1", text="looking"),
            ToolStarted(run_id="r1", call=call),
            imported("bek", "notes"),
            ToolEnded(run_id="r1", call_id="c1", ok=True, output="a.txt"),
            MessageEnded(run_id="r1", message_id="m2", text="done"),
            RunEnded(run_id="r1", reason=RunEndReason.STOP),
            prompt("p2", "second"),
            RunStarted(run_id="r2", prompt_id="p2", provenance=HOST),
        ),
        names={"p_host": "vlad"},
        texts={},
    )
    assert kinds(messages) == [
        "UserTurn",
        "AssistantTurn",
        "ToolResultTurn",
        "AssistantTurn",
        "NotesTurn",
        "UserTurn",
    ]
    assert isinstance(messages[2], ToolResultTurn)
    assert isinstance(messages[4], NotesTurn)
    assert isinstance(messages[5], UserTurn)
    assert isinstance(messages[1], AssistantTurn)
    assert messages[1].tool_calls[0].id == "c1"


def test_notes_given_in_the_last_run_are_not_lost() -> None:
    messages = replay(
        records(
            prompt("p1", "first"),
            RunStarted(run_id="r1", prompt_id="p1", provenance=HOST),
            imported("bek", "notes"),
        ),
        names={"p_host": "vlad"},
        texts={},
    )
    assert kinds(messages) == ["UserTurn", "NotesTurn"]
