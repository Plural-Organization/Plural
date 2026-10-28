from datetime import datetime

from plural.core.errors import Conflict, NotFound
from plural.protocol.events import AdmissionChanged, JoinRequested, JoinResolved
from plural.protocol.models import (
    AdmissionMode,
    JoinDecision,
    JoinRequestView,
    SessionState,
)


def request(
    state: SessionState,
    *,
    request_id: str,
    name: str,
    client: str,
    now: datetime,
    limit: int,
) -> JoinRequested:
    if len(state.join_requests) >= limit:
        raise Conflict("too many people are waiting to join, try again in a minute")
    view = JoinRequestView(id=request_id, name=name, client=client, requested_at=now)
    return JoinRequested(request=view)


def resolve(
    state: SessionState, request_id: str, decision: JoinDecision, decided_by: str | None
) -> JoinResolved:
    if request_id not in state.join_requests:
        raise NotFound("that join request is gone")
    return JoinResolved(request_id=request_id, decision=decision, decided_by=decided_by)


def abandon_all(state: SessionState, decision: JoinDecision) -> tuple[JoinResolved, ...]:
    return tuple(
        JoinResolved(request_id=request_id, decision=decision) for request_id in state.join_requests
    )


def set_admission(state: SessionState, mode: AdmissionMode) -> AdmissionChanged | None:
    return None if state.admission is mode else AdmissionChanged(mode=mode)
