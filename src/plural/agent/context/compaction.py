"""Summaries that stand in for the older part of a conversation, as in pi.

The summary is asked for in a request of its own: a short system prompt, no tools, and the older
messages written out as text with long tool results cut to their start. A summary from an earlier
compaction is updated rather than summarized again, and the files the agent read and changed
are listed after it, so they survive any number of compactions.
"""

import json
import re
from collections.abc import Iterable, Sequence
from typing import Final

from plural.agent.context.meter import estimate_tokens
from plural.agent.loop.messages import (
    AssistantTurn,
    Message,
    NotesTurn,
    SummaryTurn,
    ToolResultTurn,
    UserTurn,
    attribute,
    kept_from,
    notes_message,
)
from plural.agent.prompts import prompt, tag

SUMMARY_SYSTEM: Final = prompt("compaction_system")
SUMMARY_PROMPT: Final = prompt("compaction")
UPDATE_PROMPT: Final = prompt("compaction_update")
# How much of a tool result the summarizer sees.
RESULT_CHARS: Final = 2000

READS: Final = frozenset({"read"})
CHANGES: Final = frozenset({"write", "edit", "multi_edit"})
READ_FILES: Final = "read-files"
MODIFIED_FILES: Final = "modified-files"


def extract_tagged(text: str, tag: str) -> str:
    tagged = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    return (tagged.group(1) if tagged else text).strip()


def extract_summary(text: str) -> str:
    return extract_tagged(text, "summary")


def _cut(text: str) -> str:
    """A long tool result's start and end, where its outcome usually is."""
    if len(text) <= RESULT_CHARS:
        return text
    half = RESULT_CHARS // 2
    left = len(text) - 2 * half
    return f"{text[:half]}\n[{left} characters the agent read are left out here]\n{text[-half:]}"


def _call(name: str, args: object) -> str:
    return f"{name}({json.dumps(args, ensure_ascii=False, sort_keys=True)})"


def serialize(messages: Iterable[Message]) -> str:
    """The conversation as plain text, so the summarizer reads it instead of continuing it."""
    parts: list[str] = []
    for message in messages:
        match message:
            case UserTurn(images=images):
                seen = f"\n[{len(images)} image(s)]" if images else ""
                parts.append(f"{attribute(message)}{seen}")
            case AssistantTurn(text=text, tool_calls=calls):
                if text:
                    parts.append(f"[agent]\n{text}")
                if calls:
                    called = "; ".join(_call(call.name, call.args) for call in calls)
                    parts.append(f"[agent calls] {called}")
            case ToolResultTurn(name=name, content=content, is_error=is_error):
                failed = " failed" if is_error else ""
                parts.append(f"[{name or 'tool'} result{failed}]\n{_cut(content)}")
            case NotesTurn(source=source, text=text):
                parts.append(notes_message(source, text))
            case SummaryTurn():
                pass
    return "\n\n".join(parts)


def summary_request(history: Sequence[Message], previous: str | None) -> str:
    parts = [tag("conversation", serialize(history))]
    if previous is not None:
        parts.append(tag("previous_summary", _without_files(previous)))
        parts.append(UPDATE_PROMPT)
    parts.append(SUMMARY_PROMPT)
    return "\n\n".join(parts)


def _listed(text: str, name: str) -> list[str]:
    found = re.search(rf"<{name}>\n(.*?)\n</{name}>", text, re.DOTALL)
    return found.group(1).splitlines() if found else []


def _without_files(summary: str) -> str:
    for name in (READ_FILES, MODIFIED_FILES):
        summary = re.sub(rf"\n*<{name}>\n.*?\n</{name}>", "", summary, flags=re.DOTALL)
    return summary.strip()


def with_files(summary: str, history: Iterable[Message], previous: str | None) -> str:
    """The summary followed by the files read and changed, the earlier summary's included."""
    read = set(_listed(previous, READ_FILES)) if previous else set[str]()
    changed = set(_listed(previous, MODIFIED_FILES)) if previous else set[str]()
    for message in history:
        if not isinstance(message, AssistantTurn):
            continue
        for call in message.tool_calls:
            path = call.args.get("path")
            if not isinstance(path, str) or not path:
                continue
            if call.name in CHANGES:
                changed.add(path)
            elif call.name in READS and not path.startswith("output:"):
                read.add(path)
    sections = [
        f"<{name}>\n" + "\n".join(sorted(paths)) + f"\n</{name}>"
        for name, paths in ((READ_FILES, read - changed), (MODIFIED_FILES, changed))
        if paths
    ]
    return "\n\n".join([_without_files(summary), *sections])


class CompactionFailed(Exception):
    pass


def cut(conversation: Sequence[Message], start: int, budget: int) -> int | None:
    """Where the kept part begins: about `budget` tokens from the end, at a prompt or at a turn
    that calls tools, so a tool result never loses its call. None keeps nothing."""
    points = [
        index
        for index in range(start + 1, len(conversation))
        if kept_from(conversation[index]) is not None
    ]
    size = 0
    for index in range(len(conversation) - 1, start, -1):
        size += estimate_tokens(conversation[index])
        if size >= budget:
            return next((point for point in points if point >= index), None)
    return None


def compacted(summary: str, tail: Sequence[Message], prompt: UserTurn | None) -> list[Message]:
    """The conversation after a compaction: the summary, the run's prompt, the kept turns.

    Thinking blocks are bound to the history they were written after, which the summary
    replaces; the kept turns go on with their text and tool calls only. The prompt is put back
    after the summary unless it is among the kept turns already.
    """
    kept = [
        message.model_copy(update={"native": None})
        if isinstance(message, AssistantTurn)
        else message
        for message in tail
    ]
    kept_prompt = prompt is not None and any(
        isinstance(message, UserTurn) and message.id == prompt.id for message in kept
    )
    return [
        SummaryTurn(text=summary),
        *([prompt] if prompt is not None and not kept_prompt else []),
        *kept,
    ]
