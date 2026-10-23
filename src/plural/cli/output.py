import asyncio
import sys

from rich.console import Console
from rich.text import Text

from plural.client.connection import CommandRejected
from plural.client.presenter import Line, describe
from plural.client.reconnect import SessionClient
from plural.protocol.commands import PromptSubmit, RunAbort


def to_text(line: Line) -> Text:
    return Text(line.text, style=line.style)


async def stream(client: SessionClient, console: Console) -> None:
    async with asyncio.TaskGroup() as group:
        group.create_task(_print_events(client, console))
        group.create_task(_read_prompts(client, console))


async def _print_events(client: SessionClient, console: Console) -> None:
    async for event in client.events():
        line = describe(event, client.projection.state)
        if line is not None:
            console.print(to_text(line))


async def _read_prompts(client: SessionClient, console: Console) -> None:
    while raw := await asyncio.to_thread(sys.stdin.readline):
        text = raw.strip()
        if not text:
            continue
        command = RunAbort() if text == "/abort" else PromptSubmit(text=text)
        try:
            await client.send(command)
        except (CommandRejected, ConnectionError, TimeoutError) as error:
            console.print(Text(str(error), style="red"))
