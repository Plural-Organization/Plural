from collections.abc import Iterable
from typing import Literal

from plural.agent.providers.base import LlmMessage, NativeContent, ToolCallRequest
from plural.protocol.models import Actor, Model, Origin, Provenance


class UserTurn(Model):
    kind: Literal["user"] = "user"
    id: str
    author: Actor
    provenance: Provenance
    text: str


class AssistantTurn(Model):
    kind: Literal["assistant"] = "assistant"
    text: str = ""
    tool_calls: tuple[ToolCallRequest, ...] = ()
    native: NativeContent | None = None


class ToolResultTurn(Model):
    kind: Literal["tool_result"] = "tool_result"
    call_id: str
    name: str
    content: str
    is_error: bool = False


Message = UserTurn | AssistantTurn | ToolResultTurn


def attribute(turn: UserTurn) -> str:
    if turn.provenance.origin is Origin.PROPOSAL:
        return f"[{turn.author.name}, proposal approved by host]\n{turn.text}"
    return f"[{turn.author.name}]\n{turn.text}"


def to_llm(messages: Iterable[Message]) -> tuple[LlmMessage, ...]:
    return tuple(_convert(message) for message in messages)


def _convert(message: Message) -> LlmMessage:
    match message:
        case UserTurn():
            return LlmMessage(role="user", content=attribute(message))
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
