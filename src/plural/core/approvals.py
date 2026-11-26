from plural.core.errors import Forbidden, Invalid, NotFound
from plural.protocol.events import ApprovalResolved
from plural.protocol.models import ApprovalDecision, Participant, Role, SessionState

FOLDER_ONLY = frozenset({ApprovalDecision.READ, ApprovalDecision.WRITE})
FOLDER_ANSWERS = FOLDER_ONLY | {ApprovalDecision.REJECT}
# What a person the host named as an approver may answer: this call, once, or no. A rule that lasts
# (`always`, `block`) and a folder outside the session stay with the host (ADR 0018).
APPROVER_ANSWERS = frozenset({ApprovalDecision.ONCE, ApprovalDecision.REJECT})


def authorize_response(
    state: SessionState, *, approval_id: str, decision: ApprovalDecision, responder: Participant
) -> None:
    """Refuses an answer from anyone but the host or an approver, outside their reach."""
    if responder.role is Role.HOST:
        return
    approval = state.approvals.get(approval_id)
    if approval is None:
        raise NotFound(f"approval {approval_id}")
    if responder.role is not Role.PARTICIPANT or responder.id not in state.approvers:
        raise Forbidden("only the host or an approver the host named can answer")
    if approval.provenance.initiator_id == responder.id:
        raise Forbidden("you cannot approve what your own prompt started")
    if approval.folder is not None:
        raise Forbidden("a folder outside the session is answered by the host")
    if decision not in APPROVER_ANSWERS:
        raise Forbidden("an approver answers once or reject; rules are the host's")


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
