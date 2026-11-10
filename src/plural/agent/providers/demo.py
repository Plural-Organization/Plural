"""The demo agent: a scripted provider that needs no model, to try the interface."""

import asyncio
from collections.abc import AsyncIterator

from pydantic import JsonValue

from plural.agent.providers.base import (
    LlmEvent,
    LlmRequest,
    Stop,
    TextDelta,
    ToolCallReady,
    ToolCallRequest,
)
from plural.agent.providers.preset import Preset


def reply(text: str) -> tuple[LlmEvent, ...]:
    return (TextDelta(text=text), Stop())


def use_tool(name: str, call_id: str = "call_1", **args: JsonValue) -> tuple[LlmEvent, ...]:
    call = ToolCallRequest(id=call_id, name=name, args=args)
    return (ToolCallReady(call=call), Stop(reason="tool_use"))


class DemoProvider:
    def __init__(self) -> None:
        self._counter = 0

    async def stream(
        self, request: LlmRequest, *, cancel: asyncio.Event
    ) -> AsyncIterator[LlmEvent]:
        last = request.messages[-1]
        if last.role == "tool":
            turn = reply(f"Tool output:\n{last.content[:2000]}")
        else:
            self._counter += 1
            text = last.content.splitlines()[-1].strip()
            call_id = f"demo_{self._counter}"
            turn = (
                use_tool("bash", call_id, command=text[2:])
                if text.startswith("$ ")
                else use_tool("ls", call_id, path=".")
            )
        for event in turn:
            if cancel.is_set():
                return
            await asyncio.sleep(0)
            yield event


PRESET = Preset(
    id="demo",
    label="Demo agent",
    adapter="fake",
    hint="A scripted agent that needs nothing, to try the interface",
    connection="local",
)
