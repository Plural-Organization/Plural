from plural.core.errors import Invalid, NotFound
from plural.protocol.events import ApprovalResolved
from plural.protocol.models import ApprovalDecision, SessionState

FOLDER_ONLY = frozenset({ApprovalDecision.READ, ApprovalDecision.WRITE})
FOLDER_ANSWERS = FOLDER_ONLY | {ApprovalDecision.REJECT}


def resolve(
    state: SessionState, *, approval_id: str, decision: ApprovalDecision, resolved_by: str
) -> ApprovalResolved:
    approval = state.approvals.get(approval_id)
    if approval is None:
        raise NotFound(f"approval {approval_id}")
    if approval.folder is None and decision in FOLDER_ONLY:
        raise Invalid(f"{decision} answers a folder request, not a tool call")
    if approval.folder is not None and decision not in FOLDER_ANSWERS:
        raise Invalid("a folder request is answered with read, write or reject")
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
