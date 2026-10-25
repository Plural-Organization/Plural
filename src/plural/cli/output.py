import asyncio
import sys

from rich.console import Console
from rich.text import Text

from plural.client.connection import CommandRejected
from plural.client.presenter import Line, describe, history, rule_line
from plural.client.reconnect import SessionClient
from plural.client.slash import ShowPolicy, SlashError, parse
from plural.protocol.commands import ContextCompact, PromptSubmit
from plural.protocol.events import SessionSnapshot


def to_text(line: Line) -> Text:
    return Text(line.text, style=line.style)


async def stream(client: SessionClient, console: Console) -> None:
    async with asyncio.TaskGroup() as group:
        group.create_task(_print_events(client, console))
        group.create_task(_read_prompts(client, console))


async def _print_events(client: SessionClient, console: Console) -> None:
    async for event in client.events():
        if isinstance(event, SessionSnapshot):
            for line in history(client.projection.state):
                console.print(to_text(line))
        line = describe(event, client.projection.state)
        if line is not None:
            console.print(to_text(line))


async def _read_prompts(client: SessionClient, console: Console) -> None:
    while raw := await asyncio.to_thread(sys.stdin.readline):
        text = raw.strip()
        if not text:
            continue
        try:
            parsed = parse(text)
            if isinstance(parsed, ShowPolicy):
                _print_policy(client, console)
                continue
            await client.send(parsed or PromptSubmit(text=text))
            if isinstance(parsed, ContextCompact):
                console.print(
                    Text("the context will be compacted before the next prompt", style="dim")
                )
        except SlashError as error:
            console.print(Text(str(error), style="red"))
        except (CommandRejected, ConnectionError, TimeoutError) as error:
            console.print(Text(str(error), style="red"))


def _print_policy(client: SessionClient, console: Console) -> None:
    projection = client.projection
    for rule in projection.base_policy:
        console.print(Text(f"  {rule_line(rule)}", style="dim"))
    for rule in projection.state.policy:
        console.print(Text(f"* {rule_line(rule)}  [{rule.id}]"))
