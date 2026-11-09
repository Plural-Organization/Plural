import asyncio
import json
from datetime import UTC, datetime
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape

from plural.host.account import AccountError, AccountStore, claim, plan_line
from plural.host.config import DEFAULT_ACCOUNTS_URL, HostSettings

console = Console()


def _store() -> AccountStore:
    return AccountStore(HostSettings().state_dir)


def login(
    code: Annotated[
        str | None,
        typer.Option("--code", help="The code the web page shows, like K7QF-29XD."),
    ] = None,
    accounts: Annotated[
        str,
        typer.Option(help="The accounts service.", envvar="PLURAL_ACCOUNTS_URL"),
    ] = DEFAULT_ACCOUNTS_URL,
) -> None:
    """Link this computer to your Plural account."""
    if code is None:
        console.print("Sign in on the web, choose Start a room, and run the command it shows:")
        console.print("  plural login --code <code>")
        raise typer.Exit(2)
    try:
        entitlement = asyncio.run(claim(_store(), code, accounts))
    except AccountError as error:
        console.print(f"[red]{escape(str(error))}[/red]")
        raise typer.Exit(1) from error
    console.print(
        f"Linked to {escape(entitlement.email)}. {plan_line(entitlement, datetime.now(UTC))}."
    )


def logout() -> None:
    """Forget the account on this computer. Remove it on the web to end its access."""
    store = _store()
    if store.load() is None:
        console.print("This computer is not linked to an account.")
        return
    store.clear()
    console.print("Forgot the account on this computer. Remove it on the web to end its access.")


def whoami(
    as_json: Annotated[bool, typer.Option("--json", help="Print it for a script.")] = False,
) -> None:
    """Show the account this computer is linked to."""
    try:
        entitlement = _store().load()
    except AccountError as error:
        console.print(f"[red]{escape(str(error))}[/red]")
        raise typer.Exit(1) from error
    if entitlement is None:
        if as_json:
            print(json.dumps({"linked": False}))
        else:
            console.print("This computer is not linked to an account.")
        raise typer.Exit(1)
    now = datetime.now(UTC)
    if as_json:
        print(
            json.dumps(
                {
                    "linked": True,
                    "email": entitlement.email,
                    "plan": entitlement.plan,
                    "plan_ends_at": entitlement.plan_ends_at.isoformat(),
                    "certificate_expires_at": entitlement.expires_at.isoformat(),
                    "accounts": entitlement.accounts,
                }
            )
        )
        return
    console.print(f"{escape(entitlement.email)}")
    console.print(plan_line(entitlement, now))
