from pydantic import JsonValue

from plural.agent.context.trimming import (
    KEEP_ROUNDS,
    LONG_CHARS,
    STEP,
    shortened,
    stale_note,
    trimmed,
)
from plural.agent.loop.messages import AssistantTurn, Message, ToolResultTurn
from plural.agent.providers.base import ToolCallRequest


def age(s: "Script", rounds: int = KEEP_ROUNDS + STEP) -> None:
    """Rounds of other work, enough to make what came before them old."""
    for _ in range(rounds):
        s.call("ls", "a b c", path=".")


class Script:
    """A conversation of tool rounds, one call each."""

    def __init__(self) -> None:
        self.messages: list[Message] = []
        self._ids = 0

    def call(self, name: str, content: str, *, is_error: bool = False, **args: JsonValue) -> str:
        self._ids += 1
        call_id = f"c{self._ids}"
        self.messages.append(
            AssistantTurn(tool_calls=(ToolCallRequest(id=call_id, name=name, args=args),))
        )
        self.messages.append(
            ToolResultTurn(call_id=call_id, name=name, content=content, is_error=is_error)
        )
        return call_id


def result(messages: list[Message], call_id: str) -> str:
    return next(
        m.content for m in messages if isinstance(m, ToolResultTurn) and m.call_id == call_id
    )


def test_a_read_of_a_file_changed_later_is_replaced_with_a_note() -> None:
    s = Script()
    first = s.call("read", "old text", path="app.py")
    s.call("edit", "diff", path="app.py", old="a", new="b")
    assert result(trimmed(s.messages), first) == "old text"
    age(s)
    out = trimmed(s.messages)
    assert result(out, first) == stale_note("app.py")
    # The conversation itself keeps the result.
    assert result(s.messages, first) == "old text"


def test_the_newest_read_after_a_change_stays() -> None:
    s = Script()
    s.call("edit", "diff", path="app.py", old="a", new="b")
    latest = s.call("read", "new text", path="app.py")
    age(s)
    assert result(trimmed(s.messages), latest) == "new text"


def test_the_same_read_again_makes_the_first_one_stale() -> None:
    s = Script()
    first = s.call("read", "text", path="./app.py")
    second = s.call("read", "text", path="app.py")
    other = s.call("read", "lines 1-10", path="b.py", offset=0, limit=10)
    s.call("read", "lines 50-60", path="b.py", offset=50, limit=10)
    age(s)
    out = trimmed(s.messages)
    assert result(out, first) == stale_note("app.py")
    assert result(out, second) == "text"
    # Another part of a file is not the same read.
    assert result(out, other) == "lines 1-10"


def test_a_failed_change_does_not_make_a_read_stale() -> None:
    s = Script()
    first = s.call("read", "text", path="app.py")
    s.call("edit", "old text was not found", is_error=True, path="app.py", old="x", new="y")
    age(s)
    assert result(trimmed(s.messages), first) == "text"


def test_long_old_results_are_shortened_in_steps() -> None:
    s = Script()
    long = "\n".join(f"line {n}" for n in range(LONG_CHARS // 4))
    big = s.call("bash", long, command="pytest -v")
    small = s.call("bash", "ok", command="true")
    # Not old yet: the newest rounds are sent whole.
    for _ in range(KEEP_ROUNDS - 1):
        s.call("ls", "a b c", path=".")
    assert result(trimmed(s.messages), big) == long
    # Once a full step past the kept rounds, it is shortened, and stays the same after.
    for _ in range(STEP):
        s.call("ls", "a b c", path=".")
    out = trimmed(s.messages)
    assert result(out, big) == shortened(long, "bash")
    assert "removed to save room" in result(out, big)
    assert result(out, small) == "ok"
    s.call("ls", "a b c", path=".")
    assert result(trimmed(s.messages), big) == shortened(long, "bash")


def test_results_of_other_tools_are_never_shortened() -> None:
    s = Script()
    long = "x" * (LONG_CHARS * 2)
    kept = s.call("edit", long, path="app.py", old="a", new="b")
    for _ in range(KEEP_ROUNDS + STEP):
        s.call("ls", "a", path=".")
    assert result(trimmed(s.messages), kept) == long


def test_a_short_conversation_is_sent_unchanged() -> None:
    s = Script()
    s.call("read", "text", path="a.py")
    s.call("bash", "ok", command="make")
    assert trimmed(s.messages) == s.messages
