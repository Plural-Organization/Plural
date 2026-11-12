import asyncio
import json
import shutil
import subprocess
import sys
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
    no_daemon: Annotated[
        bool,
        typer.Option("--no-daemon", help="Do not start the background daemon the web page uses."),
    ] = False,
    daemon_port: Annotated[
        int,
        typer.Option("--daemon-port", min=1, max=65535, envvar="PLURAL_DAEMON_PORT", hidden=True),
    ] = 47831,
) -> None:
    """Link this computer to your Plural account, and start the daemon the web page talks to."""

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
    if not no_daemon:
        _start_daemon(daemon_port)


def _start_daemon(port: int) -> None:
    """Leaves the daemon running, so the web page finds this computer without another command."""
    from plural.daemon.port import PortState, start_daemon

    log = HostSettings().state_dir / "daemon.log"
    state = start_daemon(port, log)
    if state is PortState.DAEMON:
        console.print(
            "The Plural daemon is running. Go back to the web page: it finds this computer."
        )
    elif state is PortState.BUSY:
        console.print(
            f"[yellow]Port {port} is used by something else, so the daemon did not start.[/yellow]"
        )
    else:
        console.print(
            f"[yellow]The daemon did not start. Run `plural daemon`; its log: {log}[/yellow]"
        )


def _system_open(url: str) -> bool:
    """Hands `url` to the system's own opener, which returns at once whatever the browser is doing.

    `webbrowser` drives macOS through AppleScript and waits for the browser to answer, which took
    over ten seconds with a browser that was starting. False: no opener here, or it failed.
    """
    on_mac: bool = sys.platform == "darwin"
    opener = "open" if on_mac else shutil.which("xdg-open")
    if opener is None:
        return False
    try:
        subprocess.Popen(
            [opener, url],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        return False
    return True


def _open_browser(url: str) -> bool | None:
    """Asks the system to open `url`. True: done; False: it could not; None: still waiting.

    On macOS this goes through AppleScript, which waits until the browser answers, so a browser
    that is starting or stuck would hold the whole command. The address is shown either way.
    """
    if _system_open(url):
        return True
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
