import asyncio
import getpass
import json
import re
from collections.abc import Coroutine
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markup import escape

from plural.cli.format import ago
from plural.host.config import HostSettings
from plural.host.team import (
    DirectoryClient,
    TeamError,
    TeamProfile,
    TeamStore,
    create_team,
    join_team,
)
from plural.protocol.team import NAME_PATTERN, SessionStatus

team_app = typer.Typer(name="team", no_args_is_help=True, add_completion=False)
console = Console()

RelayOption = Annotated[
    str | None,
    typer.Option(help="The team's relay, wss://host or ws://host:port.", envvar="PLURAL_RELAY_URL"),
]
NameOption = Annotated[
    str | None, typer.Option("--as", help="The name teammates see. Default: your user name.")
]


def _store() -> TeamStore:
    return TeamStore(HostSettings().state_dir)


def _name(chosen: str | None) -> str:
    name = chosen or re.sub(r"[^A-Za-z0-9_.-]", "", getpass.getuser())[:32]
    if re.fullmatch(NAME_PATTERN, name) is None:
        console.print(
            "[red]A name is 1 to 32 letters, digits, dots, dashes or underscores, "
            "and starts with a letter or digit.[/red]"
        )
        raise typer.Exit(2)
    return name


def _relay(given: str | None) -> str:
    if not given:
        console.print("[red]Say which relay with --relay wss://host.[/red]")
        raise typer.Exit(2)
    return given


def _joined(store: TeamStore) -> TeamProfile:
    profile = store.load()
    if profile is None:
        console.print("[red]You are not in a team. plural team create or plural team join.[/red]")
        raise typer.Exit(1)
    return profile


def _run[T](work: Coroutine[Any, Any, T]) -> T:
    try:
        return asyncio.run(work)
    except TeamError as error:
        console.print(f"[red]{escape(str(error))}[/red]")
        raise typer.Exit(1) from error


def _already(store: TeamStore) -> None:
    current = store.load()
    if current is not None:
        console.print(
            f"[red]You are already in {escape(current.team_name)}. "
            "Leave it first with plural team leave.[/red]"
        )
        raise typer.Exit(1)


def _share(relay: str, code: str, minutes: int) -> None:
    console.print(f"Invite code [bold]{code}[/bold], valid for {minutes} minutes, one use.")
    console.print(f"Teammates run: plural team join {code} --relay {relay}", soft_wrap=True)


@team_app.command()
def create(
    name: Annotated[str, typer.Argument(help="Team name.")],
    relay: RelayOption = None,
    as_name: NameOption = None,
) -> None:
    store = _store()
    _already(store)
    address = _relay(relay)
    member = _name(as_name)

    profile = _run(create_team(address, store.identity(), team=name, member=member))
    store.save(profile)
    console.print(f"Team [bold]{escape(profile.team_name)}[/bold] created, you are {member}.")
    invite = _run(DirectoryClient(store, profile).invite())
    _share(address, invite.code, 60)


@team_app.command()
def join(
    code: Annotated[str, typer.Argument(help="Invite code from the team owner.")],
    relay: RelayOption = None,
    as_name: NameOption = None,
) -> None:
    store = _store()
    _already(store)
    address = _relay(relay)
    member = _name(as_name)
    profile = _run(join_team(address, store.identity(), code=code, member=member))
    store.save(profile)
    console.print(f"You joined [bold]{escape(profile.team_name)}[/bold] as {member}.")


@team_app.command()
def members() -> None:
    store = _store()
    listing = _run(DirectoryClient(store, _joined(store)).members())
    console.print(f"[bold]{escape(listing.team_name)}[/bold]")
    for person in listing.members:
        role = "  [dim]owner[/dim]" if person.role.value == "owner" else ""
        console.print(f"  {escape(person.name)}{role}")


@team_app.command()
def invite() -> None:
    store = _store()
    profile = _joined(store)
    created = _run(DirectoryClient(store, profile).invite())
    _share(profile.relay, created.code, 60)


@team_app.command()
def kick(name: Annotated[str, typer.Argument(help="Who to remove.")]) -> None:
    store = _store()
    removed = _run(DirectoryClient(store, _joined(store)).remove(name))
    console.print(f"{escape(removed.name)} is out of the team.")


@team_app.command()
def leave() -> None:
    store = _store()
    profile = _joined(store)
    _run(DirectoryClient(store, profile).remove(profile.member.id))
    store.clear()
    console.print(f"You left {escape(profile.team_name)}.")


@team_app.command()
def disband(yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask.")] = False) -> None:
    store = _store()
    profile = _joined(store)
    if not yes and not typer.confirm(f"Delete the team {profile.team_name} for everyone?"):
        raise typer.Exit(1)
    _run(DirectoryClient(store, profile).disband())
    store.clear()
    console.print("The team is gone.")


@team_app.command()
def status() -> None:
    profile = _store().load()
    if profile is None:
        console.print("Not in a team.")
        return
    console.print(
        f"[bold]{escape(profile.team_name)}[/bold] as {escape(profile.member.name)} "
        f"({profile.member.role.value}) on {escape(profile.relay)}"
    )


STATUS_COLORS = {
    SessionStatus.RUNNING: "green",
    SessionStatus.WAITING: "yellow",
    SessionStatus.IDLE: "dim",
}


def ls(
    as_json: Annotated[bool, typer.Option("--json", help="One JSON array, for scripts.")] = False,
) -> None:
    store = _store()
    profile = _joined(store)
    listing = _run(DirectoryClient(store, profile).sessions())
    if as_json:
        typer.echo(json.dumps([json.loads(card.model_dump_json()) for card in listing.sessions]))
        return
    if not listing.sessions:
        console.print(f"Nobody in {escape(profile.team_name)} is sharing a session right now.")
        return
    for card in listing.sessions:
        color = STATUS_COLORS[card.status]
        where = card.repo + (f" · {card.branch}" if card.branch else "")
        you = " [dim](you)[/dim]" if card.owner_id == profile.member.id else ""
        watching = f" · {card.viewers} watching" if card.viewers else ""
        console.print(
            f"[bold]{escape(card.owner)}[/bold]{you}  {escape(where)}  "
            f"[{color}]{card.status.value}[/{color}][dim]{watching} · {ago(card.updated_at)}[/dim]",
            soft_wrap=True,
        )
        if card.title:
            console.print(f"  [dim]{escape(card.title)}[/dim]", soft_wrap=True)
