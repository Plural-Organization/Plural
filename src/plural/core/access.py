from collections.abc import Mapping
from datetime import datetime, timedelta

from plural.core.errors import Conflict, NotFound
from plural.protocol.events import AccessRequested, AccessResolved, ParticipantRoleChanged
from plural.protocol.models import (
    AccessDecision,
    AccessRequestView,
    Participant,
    Role,
    SessionState,
)

COOLDOWN = timedelta(minutes=5)


def request(
    state: SessionState,
    participant: Participant,
    note: str | None,
    *,
    now: datetime,
    limit: int,
    denied_at: Mapping[str, datetime],
) -> AccessRequested:
    if participant.role is not Role.VIEWER:
        raise Conflict("you can already write")
    if participant.id in state.access_requests:
        raise Conflict("you already asked, the host has not answered yet")
    if len(state.access_requests) >= limit:
        raise Conflict("too many people are asking, try again in a few minutes")
    refused = denied_at.get(participant.id)
    if refused is not None and now - refused < COOLDOWN:
        raise Conflict("the host said no a moment ago, try again in a few minutes")
    return AccessRequested(
        request=AccessRequestView(
            participant_id=participant.id, name=participant.name, note=note, requested_at=now
        )
    )


def decide(
    state: SessionState, participant_id: str, allow: bool, decided_by: str
) -> tuple[AccessResolved | ParticipantRoleChanged, ...]:
    if participant_id not in state.access_requests:
        raise NotFound("that person is not asking for access")
    decision = AccessDecision.GRANTED if allow else AccessDecision.DENIED
    resolved = AccessResolved(
        participant_id=participant_id, decision=decision, decided_by=decided_by
    )
    if not allow:
        return (resolved,)
    return (resolved, ParticipantRoleChanged(participant_id=participant_id, role=Role.PARTICIPANT))
