from plural.core.errors import NotFound
from plural.protocol.events import ApprovalResolved
from plural.protocol.models import ApprovalDecision, SessionState


def resolve(
    state: SessionState, *, approval_id: str, decision: ApprovalDecision, resolved_by: str
) -> ApprovalResolved:
    if approval_id not in state.approvals:
        raise NotFound(f"approval {approval_id}")
    return ApprovalResolved(approval_id=approval_id, decision=decision, resolved_by=resolved_by)


def expire(state: SessionState, approval_id: str) -> ApprovalResolved | None:
    if approval_id not in state.approvals:
        return None
    return ApprovalResolved(approval_id=approval_id, decision=ApprovalDecision.REJECT)


def abandon_all(state: SessionState) -> tuple[ApprovalResolved, ...]:
    return tuple(
        ApprovalResolved(approval_id=approval_id, decision=ApprovalDecision.REJECT)
        for approval_id in state.approvals
    )
