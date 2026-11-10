"""The answer an agent CLI returns for Plural: a JSON object of text and tool calls."""

import json
from typing import cast
from uuid import uuid4

from pydantic import JsonValue

from plural.agent.providers.base import ToolCallRequest


def _string_end(raw: str, start: int) -> int | None:
    """Return the position after a complete JSON string, or None while it is partial."""
    index = start + 1
    while index < len(raw):
        char = raw[index]
        if char == '"':
            return index + 1
        if char == "\\":
            if index + 1 >= len(raw):
                return None
            index += 2
            if raw[index - 1] == "u":
                if len(raw) < index + 4:
                    return None
                index += 4
        else:
            index += 1
    return None


def _value_end(raw: str, start: int) -> int | None:
    if start >= len(raw):
        return None
    if raw[start] == '"':
        return _string_end(raw, start)
    depth = 0
    index = start
    while index < len(raw):
        char = raw[index]
        if char == '"':
            end = _string_end(raw, index)
            if end is None:
                return None
            index = end
            continue
        if char in "[{":
            depth += 1
        elif char in "]}":
            if depth == 0:
                return index
            depth -= 1
            if depth == 0:
                return index + 1
        elif char == "," and depth == 0:
            return index
        index += 1
    return None


def _text_value_start(raw: str) -> int | None:
    """Find the top-level `text` string in the incremental structured output."""
    index = 0
    while index < len(raw) and raw[index].isspace():
        index += 1
    if index >= len(raw) or raw[index] != "{":
        return None
    index += 1
    while index < len(raw):
        while index < len(raw) and (raw[index].isspace() or raw[index] == ","):
            index += 1
        if index >= len(raw) or raw[index] == "}":
            return None
        if raw[index] != '"':
            return None
        key_start = index
        key_end = _string_end(raw, index)
        if key_end is None:
            return None
        key = json.loads(raw[key_start:key_end])
        index = key_end
        while index < len(raw) and raw[index].isspace():
            index += 1
        if index >= len(raw) or raw[index] != ":":
            return None
        index += 1
        while index < len(raw) and raw[index].isspace():
            index += 1
        if key == "text":
            return index + 1 if index < len(raw) and raw[index] == '"' else None
        index = _value_end(raw, index)
        if index is None:
            return None
    return None


class TextFieldStream:
    """The `text` field of a JSON answer as it streams in, one new piece at a time."""

    def __init__(self) -> None:
        self.raw = ""
        self.start: int | None = None
        self.emitted = ""

    def feed(self, fragment: str) -> str:
        self.raw += fragment
        if self.start is None:
            self.start = _text_value_start(self.raw)
        if self.start is None:
            return ""
        end = self.start
        while end < len(self.raw):
            char = self.raw[end]
            if char == '"':
                break
            if char == "\\":
                if end + 1 >= len(self.raw):
                    break
                if self.raw[end + 1] == "u":
                    if len(self.raw) < end + 6:
                        break
                    end += 6
                else:
                    end += 2
            else:
                end += 1
        try:
            decoded = json.loads(f'"{self.raw[self.start : end]}"')
        except json.JSONDecodeError:
            return ""
        if not isinstance(decoded, str) or not decoded.startswith(self.emitted):
            return ""
        delta = decoded[len(self.emitted) :]
        self.emitted = decoded
        return delta


def _objects(raw: str) -> list[str]:
    """Every balanced top-level `{...}` in the text, outside JSON strings."""
    found: list[str] = []
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for index, char in enumerate(raw):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"' and depth > 0:
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
            if depth == 0:
                found.append(raw[start : index + 1])
    return found


def parse_answer(raw: str) -> tuple[str, list[tuple[str, dict[str, object]]]] | None:
    """The text and tool calls of the last answer object in a reply, or None without one.

    A model asked for bare JSON may still wrap it in a code fence or a sentence, so the last
    object that has `text` or `tool_calls` is taken wherever it sits.
    """
    for candidate in reversed(_objects(raw)):
        try:
            decoded: object = json.loads(candidate)
        except ValueError:
            continue
        if not isinstance(decoded, dict):
            continue
        answer = cast("dict[str, object]", decoded)
        if not ({"text", "tool_calls"} & answer.keys()):
            continue
        text = answer.get("text")
        calls: list[tuple[str, dict[str, object]]] = []
        raw_calls = answer.get("tool_calls")
        for raw_call in cast("list[object]", raw_calls) if isinstance(raw_calls, list) else []:
            if not isinstance(raw_call, dict):
                continue
            call = cast("dict[str, object]", raw_call)
            name = call.get("name")
            args = call.get("args", call.get("arguments", {}))
            if isinstance(name, str) and isinstance(args, dict):
                calls.append((name, cast("dict[str, object]", args)))
        return (text if isinstance(text, str) else ""), calls
    return None


def tool_call(raw: object, prefix: str = "toolu") -> ToolCallRequest:
    """One tool call of a structured answer, as Plural runs it.

    A call it cannot use still goes on, with a parse error the run sends back to the model as
    the call's result: one bad call should cost the model a retry, not end the run. `args` may be
    an object, or a JSON-encoded one as a strict schema has it.
    """
    call_id = f"{prefix}_{uuid4().hex}"
    if not isinstance(raw, dict):
        return ToolCallRequest(id=call_id, name="unknown", parse_error="a tool call is an object")
    call = cast("dict[str, object]", raw)
    name = call.get("name")
    if not isinstance(name, str) or not name:
        return ToolCallRequest(id=call_id, name="unknown", parse_error="a tool call needs a name")
    args: object = call.get("args", call.get("arguments", {}))
    if isinstance(args, str):
        try:
            args = cast("object", json.loads(args)) if args.strip() else {}
        except ValueError as error:
            return ToolCallRequest(
                id=call_id, name=name, parse_error=f"args are not valid JSON: {error}"
            )
    if not isinstance(args, dict):
        return ToolCallRequest(id=call_id, name=name, parse_error="args must be a JSON object")
    return ToolCallRequest(id=call_id, name=name, args=cast("dict[str, JsonValue]", args))
