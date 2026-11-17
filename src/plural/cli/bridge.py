import asyncio
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape

from plural import __version__
from plural.host.config import HostSettings

console = Console()
bridge_app = typer.Typer(help="Talk to your sessions from a chat app.", no_args_is_help=True)


@bridge_app.command()
def telegram(
    token: Annotated[
        str,
        typer.Option(
            help="The bot's token from @BotFather.",
            envvar="PLURAL_TELEGRAM_TOKEN",
            show_default=False,
        ),
    ],
    pair: Annotated[
        bool, typer.Option("--pair", help="Print a new code to pair one more owner.")
    ] = False,
) -> None:
    """Connect a Telegram bot to the sessions running on this computer."""
    from plural.bridge.bridge import Bridge
    from plural.bridge.store import BridgeStore
    from plural.bridge.telegram import Telegram, TelegramApi, TelegramError
    from plural.protocol.commands import ClientInfo
    from plural.storage.running import running_rooms

    settings = HostSettings()
    try:
        store = BridgeStore(settings.state_dir, "telegram")
    except ValueError as error:
        console.print(f"[red]{escape(str(error))}[/red]")
        raise typer.Exit(1) from error
    platform = Telegram(TelegramApi(token.strip()))
    bridge = Bridge(
        platform,
        store,
        rooms=lambda: running_rooms(settings.state_dir),
        client=ClientInfo(kind="telegram", version=__version__),
    )

    async def main() -> None:
        await platform.start()
        console.print(
            f"Bridge running as [bold]@{escape(platform.username)}[/bold]. Ctrl+C stops it."
        )
        if pair or not store.owners:
            code = store.pairing_code(renew=pair)
            console.print(
                f"To own the bot, send [bold]/pair {code}[/bold] to @{escape(platform.username)} "
                "in a private chat."
            )
        else:
            console.print(f"Owners: {escape(', '.join(store.owners.values()))}")
        await bridge.run()

    try:
        asyncio.run(main())
    except TelegramError as error:
        console.print(f"[red]Telegram: {escape(str(error))}[/red]")
        raise typer.Exit(1) from error
    except KeyboardInterrupt:
        pass
