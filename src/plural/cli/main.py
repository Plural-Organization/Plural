import asyncio
import getpass
import sys
from contextlib import suppress
from pathlib import Path
from typing import Annotated

import structlog
import typer
import uvicorn
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from plural import __version__
from plural.cli.output import stream
from plural.client.reconnect import JoinLink, SessionClient
from plural.host.bootstrap import ConfigError, build_host
from plural.host.config import HostSettings
from plural.protocol.commands import ClientInfo
from plural.protocol.models import Role
from plural.relay.app import create_app
from plural.storage.jsonl_export import export_jsonl
from plural.storage.sqlite_store import SqliteEventStore
from plural.tui.app import PluralApp

app = typer.Typer(name="plural", no_args_is_help=True, add_completion=False)
console = Console()


@app.command()
def host(
    workspace: Annotated[Path, typer.Option(help="Project directory the agent works in.")] = Path(
        "."
    ),
    bind: Annotated[str, typer.Option(help="Address for direct mode.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port for direct mode.")] = 7777,
    relay: Annotated[str | None, typer.Option(help="Relay URL; direct mode when omitted.")] = None,
    public_url: Annotated[str | None, typer.Option(help="Public ws(s) URL for links.")] = None,
    room: Annotated[str | None, typer.Option(help="Resume an existing room.")] = None,
    name: Annotated[str, typer.Option(help="Host display name.")] = getpass.getuser(),
    headless: Annotated[bool, typer.Option(help="Run without the TUI.")] = False,
) -> None:
    settings = HostSettings(
        workspace=workspace,
        bind_host=bind,
        port=port,
        relay_url=relay,
        public_url=public_url,
        room=room,
        host_name=name,
    )
    try:
        asyncio.run(_host(settings, headless=headless))
    except ConfigError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(1) from error


async def _host(settings: HostSettings, *, headless: bool) -> None:
    _configure_logging(None if headless else settings.state_dir / "logs" / "host.log")
    plural_host = await build_host(settings)
    invite = plural_host.invites.create(Role.PARTICIPANT, settings.invite_ttl_s)
    console.print(
        Panel(
            f"[bold]Guest link[/bold] (one-time)\n{invite.link}\n\n"
            f"[bold]Host link[/bold]\n{plural_host.host_link}",
            title=f"room {plural_host.room}",
        )
    )
    try:
        if headless:
            await plural_host.serve()
            return
        server = asyncio.create_task(plural_host.serve())
        client = SessionClient(
            JoinLink.parse(plural_host.host_link),
            name=settings.host_name,
            client=ClientInfo(kind="tui", version=__version__),
        )
        await PluralApp(client).run_async()
        server.cancel()
        with suppress(asyncio.CancelledError):
            await server
    finally:
        await plural_host.close()


@app.command()
def join(
    link: Annotated[str, typer.Argument(help="Invite or host link (ws:// or wss://).")],
    name: Annotated[str, typer.Option(help="Display name.")] = getpass.getuser(),
    plain: Annotated[bool, typer.Option(help="Print the stream instead of the TUI.")] = False,
) -> None:
    try:
        parsed = JoinLink.parse(link)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    client = SessionClient(
        parsed, name=name, client=ClientInfo(kind="cli" if plain else "tui", version=__version__)
    )
    if plain:
        _configure_logging(None)
        asyncio.run(stream(client, console))
    else:
        _configure_logging(HostSettings().state_dir / "logs" / "client.log")
        PluralApp(client).run()


@app.command()
def relay(
    bind: Annotated[str, typer.Option(help="Bind address.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port.")] = 8787,
) -> None:
    uvicorn.run(create_app(), host=bind, port=port, log_level="info", ws_max_size=4 * 1024 * 1024)


@app.command()
def doctor(
    workspace: Annotated[Path, typer.Option(help="Project directory to check.")] = Path("."),
) -> None:
    settings = HostSettings(workspace=workspace)
    checks = [
        ("python >= 3.12", sys.version_info >= (3, 12), sys.version.split()[0]),
        ("workspace exists", settings.workspace.is_dir(), str(settings.workspace.resolve())),
        ("data dir", _writable(settings.state_dir), str(settings.state_dir)),
        (
            "provider",
            settings.provider == "fake" or settings.api_key is not None,
            f"{settings.provider}" + ("" if settings.api_key else " (no API key)"),
        ),
    ]
    table = Table("check", "status", "detail")
    for title, ok, detail in checks:
        table.add_row(title, "[green]ok[/green]" if ok else "[red]fail[/red]", detail)
    console.print(table)
    if not all(ok for _, ok, _ in checks):
        raise typer.Exit(1)


@app.command()
def export(
    room: Annotated[str, typer.Argument(help="Room id to export.")],
    out: Annotated[Path, typer.Option(help="Destination JSONL file.")] = Path("session.jsonl"),
) -> None:
    async def run() -> int:
        store = await SqliteEventStore.open(HostSettings().state_dir / "sessions" / f"{room}.db")
        try:
            return await export_jsonl(store, out)
        finally:
            await store.close()

    console.print(f"exported {asyncio.run(run())} events to {out}")


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    probe = path / ".doctor"
    try:
        probe.write_text("ok")
        probe.unlink()
    except OSError:
        return False
    return True


def _configure_logging(path: Path | None) -> None:
    processors: list[structlog.typing.Processor] = [
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ]
    if path is None:
        structlog.configure(
            processors=processors, logger_factory=structlog.PrintLoggerFactory(sys.stderr)
        )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    structlog.configure(
        processors=processors,
        logger_factory=structlog.WriteLoggerFactory(file=path.open("a", encoding="utf-8")),
    )
