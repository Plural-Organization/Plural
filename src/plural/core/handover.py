"""Who may hand the host's seat to whom, and what each answer does (ADR 0019)."""

from plural.core.errors import Conflict, Forbidden, Invalid, NotFound
from plural.protocol.events import (
    HostHandedOver,
    HostHandoverAccepted,
    HostHandoverEnded,
    HostHandoverOffered,
)
from plural.protocol.models import (
    HandoverEnd,
    HandoverView,
    Participant,
    Role,
    SessionState,
)


def offer(state: SessionState, *, participant_id: str) -> HostHandoverOffered:
    if state.handover is not None:
        raise Conflict(f"the host is already being handed to {state.handover.name}")
    person = state.participants.get(participant_id)
    if person is None:
        raise NotFound(f"participant {participant_id}")
    if person.role is not Role.PARTICIPANT:
        raise Invalid("the host can be handed to a participant who can write, not to a viewer")
    if not person.connected:
        raise Invalid(f"{person.name} is not here to take it")
    return HostHandoverOffered(participant_id=person.id, name=person.name)


def successor(state: SessionState, who: Participant) -> HandoverView:
    """The offer that is for `who`, or why they cannot answer it."""
    if state.handover is None:
        raise Conflict("nobody is being handed the host")
    if state.handover.participant_id != who.id:
        raise Forbidden("the host was offered to someone else")
    return state.handover


def accept(state: SessionState, who: Participant) -> HostHandoverAccepted:
    if successor(state, who).accepted:
        raise Conflict("you already accepted")
    return HostHandoverAccepted(participant_id=who.id)


def end(state: SessionState, reason: HandoverEnd) -> HostHandoverEnded | None:
    return None if state.handover is None else HostHandoverEnded(reason=reason)


def handed_over(
    state: SessionState, *, former_host_id: str, former_host_name: str
) -> HostHandedOver | None:
    """The event that moves the seat, for a log that still has the successor as a participant."""
    if state.handover is None:
        return None
    return HostHandedOver(
        former_host_id=former_host_id,
        former_host_name=former_host_name,
        participant_id=state.handover.participant_id,
        name=state.handover.name,
    )
