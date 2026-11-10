import asyncio
import json
import threading
import webbrowser
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape

from plural.host.account import AccountError, AccountStore, claim, device_login
from plural.host.config import DEFAULT_ACCOUNTS_URL, HostSettings

console = Console()
# How long the address waits for the system to say the browser opened.
BROWSER_WAIT_S = 3.0


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
    no_browser: Annotated[
        bool, typer.Option("--no-browser", help="Print the address instead of opening it.")
    ] = False,
) -> None:
    """Link this computer to your Plural account."""

    def show(url: str, user_code: str) -> None:
        opened = None if no_browser else _open_browser(url)
        if no_browser or opened is False:
            console.print("Open this address to sign in:")
        elif opened is None:
            console.print("Opening your browser is slow. If nothing opens, use this address:")
        else:
            console.print("Opening your browser to sign in.")
        console.print(f"  {url}")
        console.print(
            f"Check that the page shows the code [bold]{user_code}[/bold]. Waiting for you…"
        )

    try:
        if code is None:
            work = device_login(_store(), accounts, show=show)
        else:
            work = claim(_store(), code, accounts)
        entitlement = asyncio.run(work)
    except KeyboardInterrupt as error:
        raise typer.Exit(130) from error
    except AccountError as error:
        console.print(f"[red]{escape(str(error))}[/red]")
        raise typer.Exit(1) from error
    console.print(f"Linked to {escape(entitlement.email)}.")


def _open_browser(url: str) -> bool | None:
    """Asks the system to open `url`. True: done; False: it could not; None: still waiting.

    On macOS this goes through AppleScript, which waits until the browser answers, so a browser
    that is starting or stuck would hold the whole command. The address is shown either way.
    """
    outcome: list[bool] = []
    attempt = threading.Thread(
        target=lambda: outcome.append(webbrowser.open(url)), daemon=True, name="open-browser"
    )
    attempt.start()
    attempt.join(BROWSER_WAIT_S)
    return outcome[0] if outcome else None


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
    if as_json:
        print(
            json.dumps(
                {
                    "linked": True,
                    "email": entitlement.email,
                    "certificate_expires_at": entitlement.expires_at.isoformat(),
                    "accounts": entitlement.accounts,
                }
            )
        )
        return
    console.print(f"Linked to {escape(entitlement.email)}.")
