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
from plural.host.account import AccountError, AccountStore
from plural.host.config import DEFAULT_RELAY_URL, HostSettings
from plural.host.team import (
    DirectoryClient,
    TeamError,
    TeamProfile,
    TeamStore,
    account_proof,
    account_teams,
    create_team,
    join_team,
    tunnel_closed,
)
from plural.protocol.team import NAME_PATTERN, AccountProof, SessionStatus

team_app = typer.Typer(name="team", no_args_is_help=True, add_completion=False)
console = Console()

RelayOption = Annotated[
    str | None,
    typer.Option(
        help="The team's relay, wss://host or ws://host:port. Default: the Plural relay.",
        envvar="PLURAL_RELAY_URL",
    ),
]
NameOption = Annotated[
    str | None, typer.Option("--as", help="The name teammates see. Default: your user name.")
]


def _store() -> TeamStore:
    return TeamStore(HostSettings().state_dir)


def _accounts() -> AccountStore:
    return AccountStore(HostSettings().state_dir)


def _proof() -> AccountProof | None:
    """This computer's account, when `plural login` linked it: then a team member is the account
    on every device, not this computer's key alone (ADR 0016)."""
    accounts = _accounts()
    try:
        linked = accounts.load()
    except AccountError:
        return None
    if linked is None:
        return None
    return account_proof(linked.certificate, accounts.signer().prove)


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
    return given or DEFAULT_RELAY_URL


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


def _left_closed_tunnel(store: TeamStore) -> TeamProfile | None:
    """A team made on a tunnel ends with it: leave it here, the relay is gone."""
    current = store.load()
    if current is None or not tunnel_closed(current):
        return None
    store.clear()
    console.print(
        f"[yellow]You left {escape(current.team_name)}: its tunnel is closed, "
        "and a team on a tunnel ends with it.[/yellow]"
    )
    return current


def _share(relay: str, code: str) -> None:
    console.print(f"Invite code [bold]{code}[/bold], reusable and does not expire.")
    console.print(f"Teammates run: plural team join {code} --relay {relay}", soft_wrap=True)


@team_app.command()
def create(
    name: Annotated[str, typer.Argument(help="Team name.")],
    relay: RelayOption = None,
    as_name: NameOption = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the team and the invite code as JSON.")
    ] = False,
) -> None:
    store = _store()
    _left_closed_tunnel(store)
    address = _relay(relay)
    member = _name(as_name)

    profile = _run(create_team(address, store.identity(), team=name, member=member, proof=_proof()))
    store.add(profile)
    invite = _run(DirectoryClient(store, profile).invite())
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "team": profile.team_name,
                    "relay": address,
                    "code": invite.code,
                    "minutes": None,
                    "permanent": True,
                }
            )
        )
        return
    console.print(f"Team [bold]{escape(profile.team_name)}[/bold] created, you are {member}.")
    _share(address, invite.code)


@team_app.command()
def join(
    code: Annotated[str, typer.Argument(help="Invite code from the team owner.")],
    relay: RelayOption = None,
    as_name: NameOption = None,
) -> None:
    store = _store()
    _left_closed_tunnel(store)
    address = _relay(relay)
    member = _name(as_name)
    profile = _run(join_team(address, store.identity(), code=code, member=member, proof=_proof()))
    store.add(profile)
    console.print(
        f"You joined [bold]{escape(profile.team_name)}[/bold] as {escape(profile.member.name)}. "
        "It is your current team."
    )


@team_app.command("list")
def list_teams(
    as_json: Annotated[bool, typer.Option("--json", help="One JSON array, for scripts.")] = False,
) -> None:
    """Your teams. With plural login, the account's teams on other devices come along."""
    store = _store()
    problems: list[str] = []
    accounts = _accounts()
    try:
        linked = accounts.load()
    except AccountError:
        linked = None
    if linked is not None:
        relays = [DEFAULT_RELAY_URL, *(profile.relay for profile in store.profiles())]
        for relay in dict.fromkeys(relays):
            try:
                found = asyncio.run(
                    account_teams(
                        relay, store.identity(), linked.certificate, accounts.signer().prove
                    )
                )
            except TeamError as error:
                problems.append(f"{relay}: {error}")
                continue
            for profile in found:
                store.keep(profile)
    current = store.load()
    teams = store.profiles()
    if as_json:
        typer.echo(
            json.dumps(
                [
                    {
                        "id": profile.team_id,
                        "name": profile.team_name,
                        "as": profile.member.name,
                        "role": profile.member.role.value,
                        "relay": profile.relay,
                        "current": current is not None and current.team_id == profile.team_id,
                    }
                    for profile in teams
                ]
            )
        )
        return
    if not teams:
        console.print("You are in no team. plural team create or plural team join.")
    for profile in teams:
        mark = "*" if current is not None and current.team_id == profile.team_id else " "
        role = "  [dim]owner[/dim]" if profile.member.role.value == "owner" else ""
        console.print(
            f"{mark} [bold]{escape(profile.team_name)}[/bold] as {escape(profile.member.name)}"
            f"{role}  [dim]{escape(profile.relay)}[/dim]",
            soft_wrap=True,
        )
    for problem in problems:
        console.print(f"[yellow]Could not ask {escape(problem)}[/yellow]", soft_wrap=True)


@team_app.command()
def use(
    team: Annotated[str, typer.Argument(help="The team's name or id, see plural team list.")],
) -> None:
    """Make another of your teams the current one."""
    store = _store()
    matches = [
        profile
        for profile in store.profiles()
        if profile.team_id == team or profile.team_name.lower() == team.lower()
    ]
    if len(matches) != 1:
        problem = "Several teams have that name, use its id" if matches else "No team by that name"
        console.print(f"[red]{problem}. See plural team list.[/red]")
        raise typer.Exit(1)
    try:
        chosen = store.use(matches[0].team_id)
    except TeamError as error:
        console.print(f"[red]{escape(str(error))}[/red]")
        raise typer.Exit(1) from error
    console.print(f"Your current team is [bold]{escape(chosen.team_name)}[/bold].")


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
    _share(profile.relay, created.code)


@team_app.command()
def kick(name: Annotated[str, typer.Argument(help="Who to remove.")]) -> None:
    store = _store()
    removed = _run(DirectoryClient(store, _joined(store)).remove(name))
    console.print(f"{escape(removed.name)} is out of the team.")


@team_app.command()
def leave() -> None:
    store = _store()
    if _left_closed_tunnel(store) is not None:
        return
    profile = _joined(store)
    _run(DirectoryClient(store, profile).remove(profile.member.id))
    store.clear()
    console.print(f"You left {escape(profile.team_name)}.")


@team_app.command()
def disband(yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask.")] = False) -> None:
    store = _store()
    if _left_closed_tunnel(store) is not None:
        return
    profile = _joined(store)
    if not yes and not typer.confirm(f"Delete the team {profile.team_name} for everyone?"):
        raise typer.Exit(1)
    _run(DirectoryClient(store, profile).disband())
    store.clear()
    console.print("The team is gone.")


@team_app.command()
def status() -> None:
    store = _store()
    _left_closed_tunnel(store)
    profile = store.load()
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
        for conflict in card.conflicts:
            files = ", ".join(conflict.paths[:3]) + (" …" if len(conflict.paths) > 3 else "")
            console.print(
                f"  [yellow]⚠ {escape(conflict.owner)} also changed {escape(files)}[/yellow]",
                soft_wrap=True,
            )
