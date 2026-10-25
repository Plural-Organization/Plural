import pytest

from plural.client.connection import CommandRejected
from plural.client.presenter import live
from plural.protocol.commands import ApprovalRespond, PromptSubmit, RunAbort
from plural.protocol.events import (
    ApprovalRequested,
    ApprovalResolved,
    MessageDelta,
    RunEnded,
)
from plural.protocol.models import ApprovalDecision, RunEndReason
from tests.e2e.support import Session


async def test_abort_during_model_call_clears_the_live_view(stalled_session: Session) -> None:
    owner = await stalled_session.owner()
    await owner.client.send(PromptSubmit(text="go"))
    await owner.next(MessageDelta)

    await owner.client.send(RunAbort())
    ended = await owner.next(RunEnded)

    assert ended.reason is RunEndReason.ABORTED
    assert ended.usage.input_tokens == 7
    assert owner.client.projection.streaming == {}
    assert live(owner.client.projection) == ""
    assert owner.client.projection.state.run is None


async def test_abort_while_approval_is_pending(session: Session) -> None:
    owner = await session.owner()
    await owner.client.send(PromptSubmit(text="check the notes"))
    approval = (await owner.next(ApprovalRequested)).approval

    await owner.client.send(RunAbort())
    resolved = await owner.next(ApprovalResolved)
    ended = await owner.next(RunEnded)

    assert resolved.approval_id == approval.id
    assert resolved.decision is ApprovalDecision.REJECT
    assert ended.reason is RunEndReason.ABORTED
    assert owner.client.projection.state.approvals == {}


async def test_late_answer_to_an_aborted_approval_is_conflict(session: Session) -> None:
    owner = await session.owner()
    await owner.client.send(PromptSubmit(text="check the notes"))
    approval = (await owner.next(ApprovalRequested)).approval
    await owner.client.send(RunAbort())
    await owner.next(RunEnded)

    with pytest.raises(CommandRejected):
        await owner.client.send(
            ApprovalRespond(approval_id=approval.id, decision=ApprovalDecision.ONCE)
        )
