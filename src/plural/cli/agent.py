import asyncio
import getpass
import sys
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from plural.agent_setup import AgentSetup, AgentSetupError, Choice, State
from plural.host.config import HostSettings

agent_app = typer.Typer(name="agent", no_args_is_help=True, add_completion=False)
console = Console()


def _setup() -> AgentSetup:
    return AgentSetup(HostSettings().state_dir)


def _fail(error: Exception) -> typer.Exit:
    console.print(f"[red]{escape(str(error))}[/red]")
    return typer.Exit(1)


def _choice(
    setup: AgentSetup,
    provider: str,
    model: str | None,
    endpoint: str | None,
    window: str | None,
    fast: str | None,
) -> Choice:
    """What was asked for, over what this provider was last set to."""
    before = setup.store.saved(provider) or Choice(preset=provider)
    return before.model_copy(
        update={
            key: value
            for key, value in {
                "model": model,
                "base_url": endpoint,
                "context_window": window,
                "fast_model": fast,
            }.items()
            if value is not None
        }
    )


ModelOption = Annotated[str | None, typer.Option("--model", help="The model id.")]
EndpointOption = Annotated[
    str | None, typer.Option("--endpoint", help="An OpenAI-compatible address.")
]
WindowOption = Annotated[str | None, typer.Option("--window", help="Tokens the server accepts.")]
FastOption = Annotated[
    str | None, typer.Option("--fast", help="A cheaper model for summaries, or off.")
]


@agent_app.command("list")
def list_providers(
    as_json: Annotated[bool, typer.Option("--json", help="Print it for a script.")] = False,
) -> None:
    """Every provider, and what each still needs here."""
    catalog = asyncio.run(_setup().catalog())
    if as_json:
        print(catalog.model_dump_json(by_alias=True))
        return
    table = Table(box=None, pad_edge=False)
    table.add_column("provider")
    table.add_column("id", no_wrap=True)
    table.add_column("status", no_wrap=True)
    table.add_column("to fix it", overflow="fold")
    for entry in catalog.presets:
        readiness = entry.readiness
        mark = "*" if entry.id == catalog.current.preset else " "
        ready = readiness.state is State.READY
        status = "[green]ready[/green]" if ready else readiness.state.value.replace("_", " ")
        fix = "" if ready else readiness.command or readiness.detail
        table.add_row(f"{mark} {escape(entry.label)}", entry.id, status, escape(fix))
    console.print(table)
    for server in catalog.local:
        models = ", ".join(server.models[:5]) or "no models"
        console.print(f"Found {escape(server.name)} at {escape(server.base_url)}: {escape(models)}")


@agent_app.command()
def key(
    provider: Annotated[str, typer.Argument(help="The provider id, see `plural agent list`.")],
    clear: Annotated[bool, typer.Option("--clear", help="Forget the saved key.")] = False,
) -> None:
    """Save a provider's API key on this computer. It is read from the terminal, not an argument."""
    setup = _setup()
    try:
        if clear:
            setup.clear_key(provider)
            console.print(f"Forgot the key for {escape(provider)}.")
            return
        secret = sys.stdin.readline() if not sys.stdin.isatty() else getpass.getpass("API key: ")
        setup.set_key(provider, secret)
    except AgentSetupError as error:
        raise _fail(error) from error
    console.print(f"Saved the key for {escape(provider)}. `plural agent use {provider}` picks it.")


@agent_app.command()
def use(
    provider: Annotated[str, typer.Argument(help="The provider id, see `plural agent list`.")],
    model: ModelOption = None,
    endpoint: EndpointOption = None,
    window: WindowOption = None,
    fast: FastOption = None,
) -> None:
    """Make a provider the agent on this computer."""
    setup = _setup()
    try:
        setup.use(_choice(setup, provider, model, endpoint, window, fast))
    except AgentSetupError as error:
        raise _fail(error) from error
    console.print(f"The agent is now {escape(provider)}.")


@agent_app.command("test")
def try_provider(
    provider: Annotated[
        str | None, typer.Argument(help="A provider id. Default: the current one.")
    ] = None,
    model: ModelOption = None,
    endpoint: EndpointOption = None,
    window: WindowOption = None,
    fast: FastOption = None,
) -> None:
    """Ask a provider one short question to see that it answers."""
    setup = _setup()
    chosen = provider or setup.store.current().preset
    try:
        message = asyncio.run(setup.test(_choice(setup, chosen, model, endpoint, window, fast)))
    except AgentSetupError as error:
        raise _fail(error) from error
    console.print(f"[green]{escape(chosen)} {escape(message)}[/green]")
