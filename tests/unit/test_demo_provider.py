import asyncio

from plural.agent.providers.base import LlmRequest, ToolCallReady
from plural.agent.providers.demo import DemoProvider


async def first_call(text: str) -> ToolCallReady:
    request = LlmRequest.model_validate(
        {"system": "", "messages": [{"role": "user", "content": text}], "tools": []}
    )
    async for event in DemoProvider().stream(request, cancel=asyncio.Event()):
        if isinstance(event, ToolCallReady):
            return event
    raise AssertionError("no tool call")


async def test_a_command_runs_even_when_the_message_tags_the_agent() -> None:
    event = await first_call("@plrl $ cat src/math.ts")
    assert event.call.name == "bash"
    assert event.call.args == {"command": "cat src/math.ts"}


async def test_anything_else_lists_the_folder() -> None:
    event = await first_call("@plrl what is here?")
    assert event.call.name == "ls"
