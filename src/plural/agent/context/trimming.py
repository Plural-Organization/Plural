"""Old tool results, shortened in what the model is sent; the conversation itself keeps them.

Two kinds go:

- A read of a file that was changed or read again the same way later: the model has to read it
  again to see it as it is, so the old copy only takes room and can mislead.
- A long result from many tool rounds ago: its head stays, with a note that it was shortened.

Only rounds before a boundary are touched, and the boundary moves in steps of `STEP` rounds.
History is otherwise append-only so the provider's prompt cache holds; this way the cached
prefix changes once per step, not on every call. The result is a pure function of the
conversation.
"""

import json
from collections.abc import Sequence
from typing import Final

from plural.agent.loop.messages import AssistantTurn, Message, ToolResultTurn
from plural.agent.providers.base import ToolCallRequest

READ: Final = "read"
CHANGES: Final = frozenset({"edit", "multi_edit", "write"})
# Results of these may be shortened once they are old.
SHORTENED: Final = frozenset({"read", "bash", "grep", "glob", "ls"})
# The newest rounds are always sent whole.
KEEP_ROUNDS: Final = 10
# Old results are shortened in steps of this many rounds.
STEP: Final = 10
# A result longer than this is shortened once it is old.
LONG_CHARS: Final = 2_000
HEAD_LINES: Final = 12


def _path(call: ToolCallRequest) -> str | None:
    value = call.args.get("path")
    return value.removeprefix("./") if isinstance(value, str) and value else None


def _read_key(call: ToolCallRequest) -> str:
    return json.dumps({**call.args, "path": _path(call)}, sort_keys=True)


def stale_note(path: str) -> str:
    return (
        f"[An earlier read of {path}, removed: the file was changed or read again later. "
        "Read it again if you need it.]"
    )


def shortened(text: str, name: str) -> str:
    lines = text.splitlines()
    head = "\n".join(lines[:HEAD_LINES])
    rest = len(lines) - HEAD_LINES
    more = f"{rest} more lines" if rest > 0 else f"{len(text) - len(head)} more characters"
    return (
        f"{head}\n[... {more} of this earlier {name} result removed to save room. "
        "Run it again if you need them.]"
    )


def trimmed(conversation: Sequence[Message]) -> list[Message]:
    """The conversation as the model is sent it, with stale and old long results shortened."""
    calls: dict[str, ToolCallRequest] = {}
    round_of: dict[str, int] = {}
    rounds = 0
    for message in conversation:
        if isinstance(message, AssistantTurn) and message.tool_calls:
            for call in message.tool_calls:
                calls[call.id] = call
                round_of[call.id] = rounds
            rounds += 1

    # Results whose file was changed, or read again the same way, after them.
    stale: set[str] = set()
    later_reads: set[str] = set()
    changed: set[str] = set()
    for message in reversed(conversation):
        if not isinstance(message, ToolResultTurn) or message.is_error:
            continue
        call = calls.get(message.call_id)
        if call is None or (path := _path(call)) is None:
            continue
        if call.name in CHANGES:
            changed.add(path)
        elif call.name == READ:
            key = _read_key(call)
            if path in changed or key in later_reads:
                stale.add(message.call_id)
            later_reads.add(key)

    # Rounds before this one are old; it moves in steps so the cached prefix rarely changes.
    old_before = ((rounds - KEEP_ROUNDS) // STEP) * STEP if rounds > KEEP_ROUNDS else 0

    out: list[Message] = []
    for message in conversation:
        if isinstance(message, ToolResultTurn) and (call := calls.get(message.call_id)):
            if message.call_id in stale and round_of[message.call_id] < old_before:
                message = message.model_copy(update={"content": stale_note(_path(call) or "")})
            elif (
                round_of[message.call_id] < old_before
                and call.name in SHORTENED
                and len(message.content) > LONG_CHARS
            ):
                message = message.model_copy(
                    update={"content": shortened(message.content, call.name)}
                )
        out.append(message)
    return out
