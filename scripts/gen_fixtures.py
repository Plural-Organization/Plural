import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from plural.client.projection import Projection
from plural.protocol.events import (
    AgentChanged,
    ApprovalRequested,
    ApprovalResolved,
    AttachmentAdded,
    ContextCompacted,
    Event,
    EventRecord,
    MessageDelta,
    MessageEnded,
    MessageStarted,
    ParticipantJoined,
    ParticipantLeft,
    ParticipantRevoked,
    ParticipantRoleChanged,
    PolicyRuleAdded,
    PolicyRuleRemoved,
    PromptAccepted,
    PromptDequeued,
    PromptModeChanged,
    ProposalApproved,
    ProposalCreated,
    ProposalRejected,
    RunEnded,
    RunStarted,
    ToolEnded,
    ToolStarted,
)
from plural.protocol.models import (
    ApprovalDecision,
    ApprovalView,
    AttachmentMeta,
    Delivery,
    DequeueReason,
    Origin,
    Participant,
    PolicyAction,
    PolicyRuleView,
    PromptMode,
    ProposalView,
    Provenance,
    Role,
    RunEndReason,
    ToolCallView,
    ToolRisk,
    Usage,
)

OUTPUT = Path(__file__).resolve().parents[1] / "client" / "test" / "fixtures" / "golden.json"
START = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)

HOST = Participant(id="p_host", name="vlad", role=Role.HOST, connected=True)
ALIA = Participant(id="p_alia", name="Alia", role=Role.PARTICIPANT, connected=True)
BEK_ONE = Participant(id="p_bek1111", name="Bek", role=Role.PARTICIPANT, connected=True)
BEK_TWO = Participant(id="p_bek2222", name="Bek", role=Role.VIEWER, connected=True)

DIRECT = Provenance(initiator_id="p_host", initiator_role=Role.HOST, origin=Origin.DIRECT)
VIA_PROPOSAL = Provenance(
    initiator_id="p_alia", initiator_role=Role.PARTICIPANT, origin=Origin.PROPOSAL
)
OPEN_GUEST = Provenance(
    initiator_id="p_alia", initiator_role=Role.PARTICIPANT, origin=Origin.DIRECT
)

LS = ToolCallView(id="t1", name="bash", risk=ToolRisk.EXEC, subject="ls -la")
EDIT = ToolCallView(id="t2", name="edit", risk=ToolRisk.WRITE, subject="calc.py")
LONG_OUTPUT = "\n".join(f"line {number}" for number in range(30))


def _approval() -> ApprovalView:
    return ApprovalView(
        id="ap_1",
        call=LS,
        provenance=VIA_PROPOSAL,
        timeout_at=START + timedelta(minutes=2),
        suggested_patterns=("ls*",),
    )


def _steps() -> list[tuple[str, Event]]:
    return [
        ("record", AgentChanged(agent="demo agent (scripted)")),
        ("record", ParticipantJoined(participant=HOST)),
        ("record", ParticipantJoined(participant=ALIA)),
        ("record", ParticipantJoined(participant=BEK_ONE)),
        ("record", ParticipantJoined(participant=BEK_TWO)),
        ("record", ParticipantRoleChanged(participant_id="p_bek2222", role=Role.PARTICIPANT)),
        ("record", ParticipantLeft(participant_id="p_bek1111")),
        ("record", PromptModeChanged(mode=PromptMode.REVIEW)),
        ("record", AgentChanged(agent="anthropic · claude-opus-5-5")),
        (
            "record",
            ProposalCreated(
                proposal=ProposalView(
                    id="pr_1", author_id="p_alia", text="check the notes", delivery=Delivery.NOW
                )
            ),
        ),
        (
            "record",
            ProposalApproved(proposal_id="pr_1", decided_by="p_host", text="check the notes"),
        ),
        (
            "record",
            ProposalCreated(
                proposal=ProposalView(
                    id="pr_2", author_id="p_alia", text="delete all", delivery=Delivery.NOW
                )
            ),
        ),
        ("record", ProposalRejected(proposal_id="pr_2", decided_by="p_host")),
        (
            "record",
            PromptAccepted(
                prompt_id="pm_1",
                author_id="p_alia",
                text="check the notes",
                delivery=Delivery.NOW,
                provenance=VIA_PROPOSAL,
            ),
        ),
        ("record", RunStarted(run_id="run_1", prompt_id="pm_1", provenance=VIA_PROPOSAL)),
        (
            "record",
            PromptAccepted(
                prompt_id="pm_q1",
                author_id="p_bek1111",
                text="then this",
                delivery=Delivery.NOW,
                provenance=OPEN_GUEST,
            ),
        ),
        (
            "record",
            PromptAccepted(
                prompt_id="pm_q2",
                author_id="p_bek1111",
                text="and later this",
                delivery=Delivery.FOLLOW_UP,
                provenance=OPEN_GUEST,
            ),
        ),
        ("record", PromptDequeued(prompt_id="pm_q1", reason=DequeueReason.DELIVERED)),
        ("record", PromptDequeued(prompt_id="pm_q2", reason=DequeueReason.CANCELLED)),
        ("observe", MessageDelta(message_id="m1", text="plan", thinking=True)),
        ("record", MessageStarted(run_id="run_1", message_id="m1")),
        ("observe", MessageDelta(message_id="m1", text="Looking ", thinking=False)),
        ("observe", MessageDelta(message_id="m1", text="around", thinking=False)),
        ("record", MessageEnded(run_id="run_1", message_id="m1", text="Looking around")),
        ("record", ToolStarted(run_id="run_1", call=LS)),
        ("record", ApprovalRequested(approval=_approval())),
        (
            "record",
            ApprovalResolved(
                approval_id="ap_1", decision=ApprovalDecision.ONCE, resolved_by="p_host"
            ),
        ),
        ("record", ToolEnded(run_id="run_1", call_id="t1", ok=True, output=LONG_OUTPUT)),
        ("record", ToolStarted(run_id="run_1", call=EDIT)),
        ("record", ToolEnded(run_id="run_1", call_id="t2", ok=False, output="denied by policy")),
        (
            "record",
            PolicyRuleAdded(
                rule=PolicyRuleView(
                    id="pl_1", tool="bash", pattern="ls *", action=PolicyAction.ALLOW
                )
            ),
        ),
        ("record", PolicyRuleRemoved(rule_id="pl_1")),
        (
            "record",
            AttachmentAdded(
                attachment=AttachmentMeta(
                    id="at_1", name="notes.md", size=12, sha256="0" * 64, owner_id="p_alia"
                )
            ),
        ),
        ("record", ContextCompacted(run_id="run_1", summary="notes were read", tokens_before=900)),
        (
            "record",
            ApprovalRequested(approval=_approval()),
        ),
        (
            "record",
            ApprovalResolved(
                approval_id="ap_1", decision=ApprovalDecision.REJECT, resolved_by=None
            ),
        ),
        (
            "record",
            PromptAccepted(
                prompt_id="pm_2",
                author_id="p_alia",
                text="again",
                delivery=Delivery.NOW,
                provenance=OPEN_GUEST,
            ),
        ),
        (
            "record",
            RunEnded(
                run_id="run_1",
                reason=RunEndReason.ERROR,
                usage=Usage(input_tokens=10, output_tokens=5),
                error="boom",
            ),
        ),
        ("record", RunEnded(run_id="run_2", reason=RunEndReason.STOP)),
        ("record", ParticipantRevoked(participant_id="p_alia")),
    ]


def _dump(model: Any) -> Any:
    return json.loads(model.model_dump_json())


def _scenario() -> dict[str, Any]:
    projection = Projection()
    steps: list[dict[str, Any]] = []
    for seq, (kind, event) in enumerate(_steps(), 1):
        step: dict[str, Any] = {"kind": kind}
        if kind == "record":
            record = EventRecord(
                seq=seq,
                id=f"e_{seq}",
                ts=START + timedelta(seconds=seq),
                actor_id=None,
                event=event,
            )
            projection.apply(record)
            step["record"] = _dump(record)
        else:
            assert isinstance(event, MessageDelta)
            projection.observe(event)
            step["event"] = _dump(event)
        step["state"] = _dump(projection.state)
        step["streaming"] = dict(projection.streaming)
        step["reasoning"] = projection.reasoning
        steps.append(step)
    return {"steps": steps}


def render() -> str:
    return json.dumps(_scenario(), indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    rendered = render()
    if "--check" in sys.argv:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != rendered:
            print("golden fixtures are stale: run scripts/gen_fixtures.py", file=sys.stderr)
            return 1
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
