from datetime import UTC, datetime

import pytest

from plural.core import chat
from plural.core.errors import Forbidden, Invalid, NotFound
from plural.core.roles import authorize
from plural.core.state import CHAT_LIMIT, reduce
from plural.host.publisher import Publisher
from plural.protocol.codec import decode_event
from plural.protocol.commands import MAX_MENTIONS, ChatSend, PromptSubmit
from plural.protocol.envelope import Envelope
from plural.protocol.events import ChatPosted, EventRecord, ParticipantJoined
from plural.protocol.models import Participant, Role, SessionState

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class SequenceIds:
    def __init__(self) -> None:
        self._count = 0

    def new(self, prefix: str) -> str:
        self._count += 1
        return f"{prefix}{self._count}"


HOST = Participant(id="p_host", name="vlad", role=Role.HOST, connected=True)
ALIA = Participant(id="p_alia", name="Alia", role=Role.PARTICIPANT, connected=True)
BEK = Participant(id="p_bek", name="Bek", role=Role.PARTICIPANT, connected=True)
VIEWER = Participant(id="p_view", name="Cleo", role=Role.VIEWER, connected=True)


def room() -> SessionState:
    state = SessionState()
    for index, who in enumerate((HOST, ALIA, BEK, VIEWER), start=1):
        record = EventRecord(
            seq=index,
            id=f"e{index}",
            ts=NOW,
            actor_id=None,
            event=ParticipantJoined(participant=who),
        )
        state = reduce(state, record)
    return state


def record(seq: int, event: ChatPosted) -> EventRecord:
    return EventRecord(seq=seq, id=f"e{seq}", ts=NOW, actor_id=event.author_id, event=event)


def test_everyone_who_takes_part_may_write_and_a_watcher_may_not() -> None:
    for who in (HOST, ALIA):
        authorize(who.role, ChatSend(text="hi"))
    with pytest.raises(Forbidden):
        authorize(VIEWER.role, ChatSend(text="hi"))
    with pytest.raises(Forbidden):
        authorize(VIEWER.role, PromptSubmit(text="hi"))


def test_a_team_message_names_its_author_and_has_no_recipient() -> None:
    posted = chat.post(room(), message_id="c_1", author=ALIA, command=ChatSend(text="hello"))
    assert (posted.author_id, posted.to, posted.mentions) == ("p_alia", None, ())


def test_a_private_message_needs_someone_else_who_takes_part() -> None:
    state = room()
    ok = chat.post(state, message_id="c_1", author=ALIA, command=ChatSend(text="x", to="p_bek"))
    assert ok.to == "p_bek"
    with pytest.raises(Invalid):
        chat.post(state, message_id="c_2", author=ALIA, command=ChatSend(text="x", to="p_alia"))
    with pytest.raises(Invalid):
        chat.post(state, message_id="c_3", author=ALIA, command=ChatSend(text="x", to="p_view"))
    with pytest.raises(NotFound):
        chat.post(state, message_id="c_4", author=ALIA, command=ChatSend(text="x", to="p_zed"))


def test_mentions_are_checked_and_made_unique() -> None:
    state = room()
    posted = chat.post(
        state,
        message_id="c_1",
        author=ALIA,
        command=ChatSend(text="x", mentions=("p_bek", "p_view", "p_bek")),
    )
    assert posted.mentions == ("p_bek", "p_view")
    with pytest.raises(NotFound):
        chat.post(
            state, message_id="c_2", author=ALIA, command=ChatSend(text="x", mentions=("p_zed",))
        )


def test_a_message_cannot_mention_a_crowd() -> None:
    crowd = ChatSend(text="x", mentions=tuple(f"p_{number}" for number in range(MAX_MENTIONS + 1)))
    with pytest.raises(Invalid):
        chat.post(room(), message_id="c_1", author=ALIA, command=crowd)


def test_who_may_see_a_message() -> None:
    private = ChatPosted(message_id="c", author_id="p_alia", text="x", to="p_bek")
    team = ChatPosted(message_id="c", author_id="p_alia", text="x")
    assert [chat.visible_to(private, who) for who in ("p_alia", "p_bek", "p_host", "p_view")] == [
        True,
        True,
        False,
        False,
    ]
    assert all(chat.visible_to(team, who) for who in ("p_alia", "p_bek", "p_host", "p_view"))


def test_the_state_sent_to_someone_holds_only_what_they_may_read() -> None:
    state = room()
    for seq, event in enumerate(
        (
            ChatPosted(message_id="c1", author_id="p_alia", text="team"),
            ChatPosted(message_id="c2", author_id="p_alia", text="to bek", to="p_bek"),
            ChatPosted(message_id="c3", author_id="p_bek", text="to alia", to="p_alia"),
        ),
        start=10,
    ):
        state = reduce(state, record(seq, event))
    assert [entry.text for entry in state.chat] == ["team", "to bek", "to alia"]
    assert [entry.text for entry in chat.state_for(state, "p_host").chat] == ["team"]
    assert [entry.text for entry in chat.state_for(state, "p_bek").chat] == [
        "team",
        "to bek",
        "to alia",
    ]
    assert chat.state_for(state, "p_host").participants == state.participants


def test_the_chat_in_the_state_is_capped() -> None:
    state = room()
    for number in range(CHAT_LIMIT + 25):
        event = ChatPosted(message_id=f"c{number}", author_id="p_alia", text=str(number))
        state = reduce(state, record(100 + number, event))
    assert len(state.chat) == CHAT_LIMIT
    assert state.chat[-1].text == str(CHAT_LIMIT + 24)


class Wire:
    def __init__(self, connection_id: str) -> None:
        self.id = connection_id
        self.sent: list[Envelope] = []

    def send(self, envelope: Envelope) -> None:
        self.sent.append(envelope)

    def close(self, reason: str) -> None:
        return None


def chats(wire: Wire) -> list[str]:
    texts: list[str] = []
    for envelope in wire.sent:
        event = decode_event(envelope)
        if isinstance(event, ChatPosted):
            texts.append(event.text)
    return texts


def test_a_private_message_is_sent_only_to_its_two_connections() -> None:
    publisher = Publisher(room="r_1", ids=SequenceIds(), clock=FixedClock())
    wires = {name: Wire(name) for name in ("alia", "bek", "host")}
    for name, participant in (("alia", "p_alia"), ("bek", "p_bek"), ("host", "p_host")):
        publisher.bind(wires[name], participant)
    publisher.publish(
        record(1, ChatPosted(message_id="c1", author_id="p_alia", text="secret", to="p_bek"))
    )
    publisher.publish(record(2, ChatPosted(message_id="c2", author_id="p_alia", text="team")))
    assert chats(wires["alia"]) == ["secret", "team"]
    assert chats(wires["bek"]) == ["secret", "team"]
    assert chats(wires["host"]) == ["team"]


def test_a_replay_of_the_log_skips_what_the_person_may_not_read() -> None:
    publisher = Publisher(room="r_1", ids=SequenceIds(), clock=FixedClock())
    wire = Wire("host")
    publisher.bind(wire, "p_host")
    publisher.deliver_record(
        wire,
        record(1, ChatPosted(message_id="c1", author_id="p_alia", text="secret", to="p_bek")),
    )
    publisher.deliver_record(
        wire,
        record(2, ChatPosted(message_id="c2", author_id="p_alia", text="team")),
    )
    assert chats(wire) == ["team"]
