import asyncio
import json
import sys
from typing import TYPE_CHECKING, Annotated, NoReturn, cast

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from plural import __version__
from plural.host.config import HostSettings

if TYPE_CHECKING:
    from plural.bridge.service import BridgeService

console = Console()
bridge_app = typer.Typer(help="Talk to your sessions from a chat app.", no_args_is_help=True)

ServiceId = Annotated[str, typer.Argument(help="telegram, discord…")]


def _service() -> "BridgeService":
    from plural.bridge.config import ConfigError
    from plural.bridge.service import BridgeService
    from plural.protocol.commands import ClientInfo
    from plural.storage.running import running_rooms

    settings = HostSettings()
    try:
        return BridgeService(
            settings.state_dir,
            rooms=lambda: running_rooms(settings.state_dir),
            client=ClientInfo(kind="chat-bridge", version=__version__),
        )
    except ConfigError as error:
        _fail(error)


def _fail(error: object) -> NoReturn:
    console.print(f"[red]{escape(str(error))}[/red]")
    raise typer.Exit(1)


def _stdin_values() -> dict[str, str]:
    """Values come from standard input as JSON, so a secret never shows in a process list."""
    try:
        raw: object = json.load(sys.stdin)
        if not isinstance(raw, dict):
            raise ValueError("expected a JSON object")
        body = cast(dict[str, object], raw)
        inner = body.get("values", body)
        if not isinstance(inner, dict):
            raise ValueError("expected a JSON object")
        return {str(key): str(value) for key, value in cast(dict[str, object], inner).items()}
    except ValueError as error:
        _fail(f"standard input must be JSON: {error}")


def _json(result: object) -> None:
    sys.stdout.write(json.dumps(result) + "\n")


@bridge_app.command("list")
def list_(
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """The chat apps this computer can connect, and how each one is doing."""
    catalog = _service().catalog()
    if as_json:
        _json({"ok": True, "providers": catalog})
        return
    table = Table(box=None, pad_edge=False)
    for column in ("app", "state", "bot", "owners", "chats"):
        table.add_column(column)
    for entry in catalog:
        owners = cast(list[object], entry["owners"])
        table.add_row(
            str(entry["id"]),
            str(entry["state"]) if entry["configured"] else "not set up",
            str(entry["identity"] or entry["error"] or "-"),
            str(len(owners)),
            str(entry["chats"]),
        )
    console.print(table)


@bridge_app.command()
def set(
    provider: ServiceId,
    value: Annotated[
        list[str] | None,
        typer.Option(
            "--value",
            "-v",
            help="A setting as name=value. Prefer --stdin for a token.",
            show_default=False,
        ),
    ] = None,
    stdin: Annotated[
        bool, typer.Option("--stdin", help='Read {"values": {...}} as JSON from standard input.')
    ] = False,
    disable: Annotated[bool, typer.Option("--disable", help="Keep the settings, stop it.")] = False,
    enable: Annotated[bool, typer.Option("--enable", help="Turn it on again.")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Add a chat app or change its settings. A running bridge picks the change up."""
    from plural.bridge.config import ConfigError

    values = _stdin_values() if stdin else {}
    for item in value or []:
        name, separator, text = item.partition("=")
        if not separator:
            _fail(f"{item!r} is not name=value")
        values[name] = text
    service = _service()
    try:
        if values or not (disable or enable):
            service.save(provider, values, enabled=False if disable else True if enable else None)
        else:
            service.set_enabled(provider, enable)
    except ConfigError as error:
        if as_json:
            _json({"ok": False, "error": str(error)})
            raise typer.Exit(1) from error
        _fail(error)
    if as_json:
        _json({"ok": True})
    else:
        console.print(f"Saved. {escape(provider)} will connect when the bridges run.")


@bridge_app.command()
def remove(provider: ServiceId, as_json: Annotated[bool, typer.Option("--json")] = False) -> None:
    """Forget a chat app's settings. Its links and owners stay, in case you add it back."""
    from plural.bridge.config import ConfigError

    try:
        _service().remove(provider)
    except ConfigError as error:
        _fail(error)
    if as_json:
        _json({"ok": True})
    else:
        console.print("Removed.")


@bridge_app.command("test")
def try_(
    provider: ServiceId,
    stdin: Annotated[
        bool, typer.Option("--stdin", help="Test values typed, not saved yet.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Connect once with the settings and say who the bot is. Nothing is saved or started."""
    from plural.bridge.config import ConfigError
    from plural.bridge.platform import PlatformError

    values = _stdin_values() if stdin else None
    try:
        identity = asyncio.run(_service().test(provider, values))
    except (ConfigError, PlatformError) as error:
        if as_json:
            _json({"ok": False, "error": str(error)})
            raise typer.Exit(1) from error
        _fail(error)
    if as_json:
        _json({"ok": True, "identity": identity})
    else:
        console.print(f"Connected as [bold]{escape(identity)}[/bold].")


@bridge_app.command()
def pair(
    provider: ServiceId,
    renew: Annotated[
        bool, typer.Option("--renew", help="A new code, to add one more owner.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """The code that makes a person the bot's owner when they send /pair <code> in private."""
    from plural.bridge.config import ConfigError

    service = _service()
    try:
        code = service.renew_pairing(provider) if renew else service.pairing(provider)
    except ConfigError as error:
        _fail(error)
    link = _open_link(service, provider, code)
    if as_json:
        _json({"ok": True, "pairing": code, "link": link})
    elif code is None:
        console.print("The bot has an owner. Use --renew to add another.")
    elif link:
        console.print(f"Open [bold]{escape(link)}[/bold] and press Start.")
    else:
        console.print(f"Send [bold]/pair {code}[/bold] to the bot in a private chat.")


def _open_link(service: "BridgeService", provider: str, code: str | None) -> str:
    """A link that makes the person an owner in one tap, when the bridge runs and the service
    takes the code from a link (Telegram does); empty otherwise."""
    for entry in service.catalog():
        links = cast("dict[str, object]", entry.get("links") or {})
        if entry["id"] == provider and links.get("autopair") and code is not None:
            return str(links.get("open", ""))
    return ""


@bridge_app.command()
def run() -> None:
    """Run every chat app that is set up, until Ctrl+C. The daemon does this too."""
    from plural.bridge.service import BridgeBusy

    service = _service()
    console.print("Running the chat bridges. Ctrl+C stops them.")
    try:
        asyncio.run(service.run())
    except BridgeBusy as error:
        _fail(error)
    except KeyboardInterrupt:
        pass


def _once(provider: str, values: dict[str, str]) -> None:
    from plural.bridge.platform import PlatformError
    from plural.bridge.providers import builtin

    spec = builtin().get(provider)
    assert spec is not None
    service = _service()
    platform = spec.build(values)

    async def main() -> None:
        await platform.start()
        console.print(
            f"Bridge running as [bold]{escape(platform.identity)}[/bold]. Ctrl+C stops it."
        )
        store = service.store(provider)
        if not store.owners:
            code = store.pairing_code()
            link = platform.links.open.replace("{code}", code) if platform.links.autopair else ""
            console.print(
                f"To own the bot, open [bold]{escape(link)}[/bold] and press Start."
                if link
                else f"To own the bot, send [bold]/pair {code}[/bold] to "
                f"{escape(platform.identity)} in a private chat."
            )
        await service.run_with(provider, platform)

    try:
        asyncio.run(main())
    except PlatformError as error:
        _fail(f"{spec.label}: {error}")
    except KeyboardInterrupt:
        pass


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
    name: Annotated[
        list[str] | None,
        typer.Option(
            "--name",
            help="A word that calls the bot when a message starts with it. "
            "Default: plural, плюрал, плурал and the bot's own name.",
        ),
    ] = None,
) -> None:
    """Run a Telegram bot once, with a token you give now. To keep it, use `bridge set telegram`."""
    _once("telegram", {"token": token, "names": ",".join(name or [])})


@bridge_app.command()
def discord(
    token: Annotated[
        str,
        typer.Option(
            help="The bot's token from the Discord Developer Portal.",
            envvar="PLURAL_DISCORD_TOKEN",
            show_default=False,
        ),
    ],
    name: Annotated[
        list[str] | None,
        typer.Option("--name", help="A word that calls the bot when a message starts with it."),
    ] = None,
) -> None:
    """Run a Discord bot once, with a token you give now. To keep it, use `bridge set discord`."""
    _once("discord", {"token": token, "names": ",".join(name or [])})
