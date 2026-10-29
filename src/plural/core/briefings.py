from collections.abc import Mapping
from datetime import datetime, timedelta

from plural.core.errors import Conflict, NotFound
from plural.protocol.events import BriefingRequested, BriefingResolved
from plural.protocol.models import (
    BriefingDecision,
    BriefingRequestView,
    BriefingSharing,
    Participant,
    SessionState,
)

COOLDOWN = timedelta(seconds=60)


def request(
    state: SessionState,
    participant: Participant,
    focus: str | None,
    update: bool,
    *,
    request_id: str,
    now: datetime,
    limit: int,
    last_at: Mapping[str, datetime],
) -> BriefingRequested:
    if state.briefing_sharing is BriefingSharing.OFF:
        raise Conflict("the host does not share briefings of this session")
    if any(ask.participant_id == participant.id for ask in state.briefing_requests.values()):
        raise Conflict("you already asked for a briefing, wait for it")
    if len(state.briefing_requests) >= limit:
        raise Conflict("too many briefings are waiting, try again in a minute")
    previous = last_at.get(participant.id)
    if previous is not None and now - previous < COOLDOWN:
        raise Conflict("wait a minute between briefings")
    return BriefingRequested(
        request=BriefingRequestView(
            id=request_id,
            participant_id=participant.id,
            name=participant.name,
            focus=focus,
            update=update,
            requested_at=now,
        )
    )


def decide(
    state: SessionState, request_id: str, allow: bool, decided_by: str | None
) -> BriefingResolved:
    ask = state.briefing_requests.get(request_id)
    if ask is None:
        raise NotFound("that briefing request is gone")
    return BriefingResolved(
        request_id=request_id,
        participant_id=ask.participant_id,
        decision=BriefingDecision.GRANTED if allow else BriefingDecision.DENIED,
        decided_by=decided_by,
    )
