"""What a chat bridge says and hears, the same for every chat service.

A platform (Telegram now, Slack later) turns its own updates into `Said` and `Pressed`, and turns
`Answer` and `Notice` into its own messages. Everything about the room lives in `room.py` and
`bridge.py`, which never see a platform's API.
"""

from dataclasses import dataclass, field
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class Place:
    """Where a conversation happens: a chat, and a topic inside it when the chat has topics."""

    platform: str
    chat: str
    thread: str | None = None
    private: bool = False

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.chat}:{self.thread or ''}"


@dataclass(frozen=True, slots=True)
class Person:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class Said:
    """A message. `addressed` is whether it was meant for the bot: a mention, a reply to the
    bot, a command or anything in a private chat."""

    place: Place
    person: Person
    text: str
    addressed: bool
    ref: str | None = None


@dataclass(frozen=True, slots=True)
class Pressed:
    """A button under one of the bot's messages, or the platform's own stop button."""

    place: Place
    person: Person
    data: str
    query: str | None = None


type Incoming = Said | Pressed


class Tone(StrEnum):
    PLAIN = "plain"
    GOOD = "good"
    DANGER = "danger"
    PRIMARY = "primary"


@dataclass(frozen=True, slots=True)
class Choice:
    label: str
    data: str
    tone: Tone = Tone.PLAIN


class StepState(StrEnum):
    RUNNING = "running"
    OK = "ok"
    FAILED = "failed"


@dataclass(slots=True)
class Step:
    call_id: str
    tool: str
    subject: str
    state: StepState = StepState.RUNNING


class Phase(StrEnum):
    THINKING = "thinking"
    WORKING = "working"
    DONE = "done"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(slots=True)
class Answer:
    """One run of the agent, as it goes: what it did and what it says."""

    asked_by: str | None = None
    question: str = ""
    steps: list[Step] = field(default_factory=list[Step])
    text: str = ""
    phase: Phase = Phase.THINKING
    error: str | None = None

    @property
    def finished(self) -> bool:
        return self.phase in (Phase.DONE, Phase.STOPPED, Phase.FAILED)


@dataclass(frozen=True, slots=True)
class Notice:
    """A message of the bot's own: a reply to a command, or a question with buttons."""

    text: str
    choices: tuple[tuple[Choice, ...], ...] = ()
