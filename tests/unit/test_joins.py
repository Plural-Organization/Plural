from datetime import UTC, datetime, timedelta

import pytest

from plural.core import joins, visibility
from plural.core.errors import Conflict, NotFound, Unauthorized
from plural.core.state import reduce
from plural.host.gateway import Admission, Gateway, NeedsApproval
from plural.host.invites import InviteBook, RoomLink
from plural.protocol.commands import ClientInfo, SessionHello
from plural.protocol.events import ChatPosted, Event, EventRecord, JoinRequested, JoinResolved
from plural.protocol.models import (
    HOST_PARTICIPANT_ID,
    AdmissionMode,
    JoinDecision,
    Role,
    SessionState,
)
from plural.security.tokens import TokenSigner

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


class Clock:
    def now(self) -> datetime:
        return NOW


class Ids:
    def __init__(self) -> None:
        self.count = 0

    def new(self, prefix: str) -> str:
        self.count += 1
        return f"{prefix}{self.count}"


def record(seq: int, event: Event) -> EventRecord:
    return EventRecord(seq=seq, id=f"e{seq}", ts=NOW, actor_id=None, event=event)


def ask(
    state: SessionState, name: str = "Dana", request_id: str = "j_1", limit: int = 5
) -> JoinRequested:
    return joins.request(
        state, request_id=request_id, name=name, client="tui 0.2.2", now=NOW, limit=limit
    )


def test_a_request_is_kept_until_it_is_resolved() -> None:
    state = reduce(SessionState(), record(1, ask(SessionState())))
    assert list(state.join_requests) == ["j_1"]
    assert state.join_requests["j_1"].name == "Dana"
    resolved = joins.resolve(state, "j_1", JoinDecision.ALLOW, HOST_PARTICIPANT_ID)
    assert reduce(state, record(2, resolved)).join_requests == {}


def test_there_is_a_limit_to_the_people_who_wait() -> None:
    state = SessionState()
    for number in range(3):
        state = reduce(state, record(number + 1, ask(state, request_id=f"j_{number}", limit=3)))
    with pytest.raises(Conflict, match="too many people are waiting"):
        ask(state, request_id="j_9", limit=3)


def test_a_request_that_is_gone_cannot_be_decided() -> None:
    with pytest.raises(NotFound):
        joins.resolve(SessionState(), "j_nope", JoinDecision.ALLOW, None)


def test_everyone_still_waiting_can_be_closed_at_once() -> None:
    state = SessionState()
    for number in range(2):
        state = reduce(state, record(number + 1, ask(state, request_id=f"j_{number}")))
    closed = joins.abandon_all(state, JoinDecision.EXPIRED)
    assert [(c.request_id, c.decision) for c in closed] == [
        ("j_0", JoinDecision.EXPIRED),
        ("j_1", JoinDecision.EXPIRED),
    ]


def test_the_admission_mode_changes_only_when_it_changes() -> None:
    state = SessionState()
    assert joins.set_admission(state, AdmissionMode.APPROVE) is None
    changed = joins.set_admission(state, AdmissionMode.OPEN)
    assert changed is not None
    assert reduce(state, record(1, changed)).admission is AdmissionMode.OPEN


def test_only_the_host_is_told_who_is_waiting() -> None:
    request = ask(SessionState())
    resolved = JoinResolved(request_id="j_1", decision=JoinDecision.DENY)
    for event in (request, resolved):
        assert visibility.visible_to(event, HOST_PARTICIPANT_ID)
        assert not visibility.visible_to(event, "p_alia")
    assert visibility.visible_to(ChatPosted(message_id="c", author_id="p_a", text="x"), "p_alia")


def test_the_state_sent_to_a_guest_does_not_list_the_people_waiting() -> None:
    state = reduce(SessionState(), record(1, ask(SessionState())))
    assert visibility.state_for(state, "p_alia").join_requests == {}
    assert list(visibility.state_for(state, HOST_PARTICIPANT_ID).join_requests) == ["j_1"]


def test_the_room_link_names_its_code_and_can_be_replaced() -> None:
    link = RoomLink(code="CODE-1", link_base="wss://h/r_1")
    assert link.link == "wss://h/r_1?join=CODE-1"
    assert link.matches("CODE-1")
    assert not link.matches("code-1")
    assert not link.matches("")
    old = link.code
    assert link.rotate() != old
    assert not link.matches(old)
    assert link.matches(link.code)
    assert len(link.code) >= 20


def gateway() -> Gateway:
    ids = Ids()
    return Gateway(
        room="r_1",
        signer=TokenSigner(
            __import__(
                "cryptography.hazmat.primitives.asymmetric.ed25519", fromlist=["x"]
            ).Ed25519PrivateKey.generate()
        ),
        invites=InviteBook(clock=Clock(), link_base="wss://h/r_1"),
        link=RoomLink(code="CODE-1", link_base="wss://h/r_1"),
        ids=ids,
        clock=Clock(),
        token_ttl_s=3600,
    )


def hello(*, join: str | None = None, token: str | None = None) -> SessionHello:
    client = ClientInfo(kind="tui", version="0.2.2")
    return SessionHello(client=client, name="Dana", join=join, token=token)


def test_the_room_link_asks_for_approval_by_default() -> None:
    result = gateway().admit(hello(join="CODE-1"), SessionState())
    assert result == NeedsApproval(name="Dana", client="tui 0.2.2")


def test_the_room_link_lets_people_in_when_the_room_is_open() -> None:
    state = SessionState(admission=AdmissionMode.OPEN)
    result = gateway().admit(hello(join="CODE-1"), state)
    assert isinstance(result, Admission)
    assert result.participant.role is Role.PARTICIPANT
    assert result.participant.name == "Dana"


def test_a_wrong_room_link_is_refused_whatever_the_mode() -> None:
    for mode in AdmissionMode:
        with pytest.raises(Unauthorized, match="no longer valid"):
            gateway().admit(hello(join="nope"), SessionState(admission=mode))


def test_a_person_who_was_approved_gets_the_role_the_host_chose() -> None:
    gate = gateway()
    viewer = gate.admit_approved("Eve", Role.VIEWER)
    assert viewer.participant.role is Role.VIEWER
    claims = gate.identify(
        viewer.token,
        SessionState(participants={viewer.participant.id: viewer.participant}),
    )
    assert claims.id == viewer.participant.id


def test_a_saved_token_is_not_asked_about_again() -> None:
    gate = gateway()
    person = gate.admit_approved("Eve", Role.PARTICIPANT)
    state = SessionState(participants={person.participant.id: person.participant})
    again = gate.admit(hello(token=person.token, join="CODE-1"), state)
    assert isinstance(again, Admission)
    assert again.participant.id == person.participant.id


def test_without_an_invite_a_link_or_a_token_nothing_is_admitted() -> None:
    with pytest.raises(Unauthorized, match="required"):
        gateway().admit(hello(), SessionState())


def test_a_waiting_request_remembers_when_it_came() -> None:
    later = NOW + timedelta(seconds=30)
    asked = joins.request(
        SessionState(), request_id="j_1", name="Dana", client="web 0.2.2", now=later, limit=5
    )
    assert asked.request.requested_at == later
