from plural.core.state import reduce
from plural.protocol.events import (
    Event,
    EventRecord,
    MessageDelta,
    MessageEnded,
    MessageStarted,
    RunEnded,
)
from plural.protocol.models import Participant, PolicyRuleView, SessionState


class Projection:
    def __init__(self) -> None:
        self.state = SessionState()
        self.streaming: dict[str, str] = {}
        self.reasoning = 0
        self.base_policy: tuple[PolicyRuleView, ...] = ()
        self.me_id: str | None = None
        self.ready = False

    @property
    def me(self) -> Participant | None:
        return self.state.participants.get(self.me_id) if self.me_id else None

    def load(self, state: SessionState, streaming: dict[str, str]) -> None:
        self.state = state
        self.streaming = dict(streaming)
        self.reasoning = 0
        self.ready = True

    def apply(self, record: EventRecord) -> bool:
        if record.seq <= self.state.last_seq:
            return False
        self.state = reduce(self.state, record)
        match record.event:
            case MessageStarted(message_id=message_id):
                self.streaming[message_id] = ""
            case MessageEnded(message_id=message_id):
                self.streaming.pop(message_id, None)
                self.reasoning = 0
            case RunEnded():
                self.streaming.clear()
                self.reasoning = 0
            case _:
                pass
        return True

    def observe(self, event: Event) -> None:
        if not isinstance(event, MessageDelta):
            return
        if event.thinking:
            self.reasoning += len(event.text)
        else:
            self.streaming[event.message_id] = self.streaming.get(event.message_id, "") + event.text
