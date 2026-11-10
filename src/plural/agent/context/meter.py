"""How big the prompt is and what it is spent on: an estimate from the text, which the loop
scales to the provider's own count once it has one."""

import json
from collections.abc import Sequence

from plural.agent.loop.messages import (
    AssistantTurn,
    Message,
    NotesTurn,
    SummaryTurn,
    ToolResultTurn,
    UserTurn,
)
from plural.agent.providers.base import ToolCallRequest, ToolSchema
from plural.protocol.models import ContextPart, ContextPartKind

Sections = tuple[tuple[ContextPartKind, str], ...]

# What a 1568 px image costs on Anthropic, the largest the terminal client sends.
IMAGE_TOKENS = 1600


def signature(call: ToolCallRequest) -> str:
    """A tool call as text: what it costs in the prompt, and what tells two calls apart."""
    return f"{call.name}:{json.dumps(call.args, sort_keys=True)}"


def estimate_tokens(message: Message) -> int:
    match message:
        case UserTurn(text=text, images=images):
            return len(text) // 4 + IMAGE_TOKENS * len(images)
        case ToolResultTurn(content=text) | SummaryTurn(text=text) | NotesTurn(text=text):
            return len(text) // 4
        case AssistantTurn(text=text, tool_calls=calls):
            return (len(text) + sum(len(signature(call)) for call in calls)) // 4


def part_of(message: Message) -> tuple[ContextPartKind, str | None]:
    match message:
        case ToolResultTurn(name=name):
            return ContextPartKind.TOOL_RESULTS, name
        case SummaryTurn():
            return ContextPartKind.SUMMARY, None
        case NotesTurn():
            return ContextPartKind.NOTES, None
        case UserTurn() | AssistantTurn():
            return ContextPartKind.MESSAGES, None


def context_parts(
    sections: Sections,
    tools: Sequence[ToolSchema],
    conversation: Sequence[Message],
    *,
    tokens: int,
    counted: bool,
) -> tuple[ContextPart, ...]:
    """What the prompt is spent on, estimated, then scaled to `tokens` when the provider has
    counted the prompt. Before its first call it has not counted the system prompt and tools."""
    sizes: dict[tuple[ContextPartKind, str | None], int] = {}
    for kind, text in sections:
        sizes[kind, None] = sizes.get((kind, None), 0) + len(text) // 4
    sizes[ContextPartKind.TOOLS, None] = sum(len(tool.model_dump_json()) for tool in tools) // 4
    for message in conversation:
        key = part_of(message)
        sizes[key] = sizes.get(key, 0) + estimate_tokens(message)
    estimated = sum(sizes.values())
    scale = tokens / estimated if counted and estimated else 1.0
    return tuple(
        ContextPart(kind=kind, name=name, tokens=round(size * scale))
        for (kind, name), size in sizes.items()
        if size
    )
