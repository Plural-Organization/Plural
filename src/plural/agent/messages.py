from collections.abc import Iterable
from typing import Literal

from plural.agent.prompts import prompt, tag
from plural.agent.providers.base import LlmImage, LlmMessage, NativeContent, ToolCallRequest
from plural.protocol.models import Actor, Model, Origin, Provenance

# Notes whose source starts with this come from a host plugin's before_run hook.
PLUGIN_SOURCE = "plugin:"


def summary_message(text: str) -> str:
    return f"{prompt('summary_note')}\n{tag('summary', text)}"


def notes_message(source: str, text: str) -> str:
    if source.startswith(PLUGIN_SOURCE):
        plugin = source.removeprefix(PLUGIN_SOURCE)
        note = prompt("plugin_note").format(plugin=plugin)
        return f"{note}\n{tag('plugin_context', text, plugin=plugin)}"
    note = prompt("briefing_note").format(source=source)
    return f"{note}\n{tag('briefing', text, source=source)}"


class UserTurn(Model):
    kind: Literal["user"] = "user"
    id: str
    author: Actor
    provenance: Provenance
    text: str
    images: tuple[LlmImage, ...] = ()


class AssistantTurn(Model):
    kind: Literal["assistant"] = "assistant"
    text: str = ""
    tool_calls: tuple[ToolCallRequest, ...] = ()
    native: NativeContent | None = None


class SummaryTurn(Model):
    kind: Literal["summary"] = "summary"
    text: str


class NotesTurn(Model):
    kind: Literal["notes"] = "notes"
    source: str
    text: str


class ToolResultTurn(Model):
    kind: Literal["tool_result"] = "tool_result"
    call_id: str
    name: str
    content: str
    is_error: bool = False


Message = UserTurn | AssistantTurn | ToolResultTurn | SummaryTurn | NotesTurn


def kept_from(message: Message) -> str | None:
    """How a compaction names the first message it kept, so replay finds it again: a prompt by
    its id, a turn by its first tool call. Other messages cannot start the kept part."""
    match message:
        case UserTurn(id=prompt_id):
            return f"prompt:{prompt_id}"
        case AssistantTurn(tool_calls=(first, *_)):
            return f"call:{first.id}"
        case _:
            return None


def _last_tool_round(items: list[Message]) -> int | None:
    for index in range(len(items) - 1, -1, -1):
        turn = items[index]
        if isinstance(turn, AssistantTurn) and turn.tool_calls:
            return index
    return None


def settled(messages: Iterable[Message]) -> list[Message]:
    """The conversation without a tool round that is still waiting for its results."""
    items = list(messages)
    while items:
        last = items[-1]
        if isinstance(last, AssistantTurn) and last.tool_calls:
            items.pop()
            continue
        if isinstance(last, ToolResultTurn):
            owner = _last_tool_round(items)
            turn = items[owner] if owner is not None else None
            if owner is not None and isinstance(turn, AssistantTurn):
                answered = {m.call_id for m in items[owner + 1 :] if isinstance(m, ToolResultTurn)}
                if not {call.id for call in turn.tool_calls} <= answered:
                    del items[owner:]
                    continue
        break
    return items


def attribute(turn: UserTurn) -> str:
    if turn.provenance.origin is Origin.PROPOSAL:
        return f"[{turn.author.name}, proposal approved by host]\n{turn.text}"
    return f"[{turn.author.name}]\n{turn.text}"


def to_llm(messages: Iterable[Message]) -> tuple[LlmMessage, ...]:
    return tuple(_convert(message) for message in messages)


def _convert(message: Message) -> LlmMessage:
    match message:
        case UserTurn():
            return LlmMessage(role="user", content=attribute(message), images=message.images)
        case SummaryTurn():
            return LlmMessage(role="user", content=summary_message(message.text))
        case NotesTurn():
            return LlmMessage(role="user", content=notes_message(message.source, message.text))
        case AssistantTurn():
            return LlmMessage(
                role="assistant",
                content=message.text,
                tool_calls=message.tool_calls,
                native=message.native,
            )
        case ToolResultTurn():
            return LlmMessage(
                role="tool",
                content=message.content,
                tool_call_id=message.call_id,
                is_error=message.is_error,
            )
