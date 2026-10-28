import asyncio
import getpass
import json
import os
import sys
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Any

import structlog
import typer
import uvicorn
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from plural import __version__
from plural.host.bootstrap import ConfigError, Host, build_host, build_provider, resolve_api_key
from plural.host.config import HostSettings
from plural.host.control import MAX_LINE_BYTES, Control, read_lines
from plural.protocol.envelope import PROTOCOL_VERSION
from plural.protocol.models import PromptMode, Role
from plural.relay.app import create_app
from plural.relay.limits import RelayLimits
from plural.storage.jsonl_export import export_jsonl
from plural.storage.sqlite_store import SqliteEventStore

app = typer.Typer(name="plural-host", no_args_is_help=True, add_completion=False)
console = Console()
DEFAULT_LIMITS = RelayLimits()


@app.command()
def host(
    workspace: Annotated[
        Path | None, typer.Option(help="Project directory the agent works in.")
    ] = None,
    bind: Annotated[str | None, typer.Option(help="Address for direct mode.")] = None,
    port: Annotated[int | None, typer.Option(help="Port for direct mode.")] = None,
    relay: Annotated[str | None, typer.Option(help="Relay URL; direct mode when omitted.")] = None,
    public_url: Annotated[str | None, typer.Option(help="Public ws(s) URL for links.")] = None,
    room: Annotated[str | None, typer.Option(help="Resume an existing room.")] = None,
    name: Annotated[str | None, typer.Option(help="Host display name.")] = None,
    prompts: Annotated[
        PromptMode | None,
        typer.Option(help="open: participants prompt directly; review: the host approves them."),
    ] = None,
    machine: Annotated[
        bool,
        typer.Option(
            "--json", help="Print one JSON line when ready, log to a file, quit when stdin closes."
        ),
    ] = False,
) -> None:
    given: dict[str, Any] = {
        "workspace": workspace,
        "bind_host": bind,
        "port": port,
        "relay_url": relay,
        "public_url": public_url,
        "room": room,
        "host_name": name,
        "prompt_mode": prompts,
    }
    options = {key: value for key, value in given.items() if value is not None}
    if name is None and "PLURAL_HOST_NAME" not in os.environ:
        options["host_name"] = getpass.getuser()
    settings = HostSettings(**options)
    try:
        asyncio.run(_host(settings, machine=machine))
    except ConfigError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(1) from error


def ready_line(room: str, guest_link: str, host_link: str) -> str:
    return json.dumps(
        {
            "type": "ready",
            "room": room,
            "guest_link": guest_link,
            "host_link": host_link,
            "version": __version__,
            "protocol": PROTOCOL_VERSION,
        }
    )


def plain_links(room: str, guest_link: str, host_link: str) -> str:
    return "\n".join(
        (
            f"room {room}",
            f"guest link (one-time): {guest_link}",
            f"host link: {host_link}",
        )
    )


async def _host(settings: HostSettings, *, machine: bool) -> None:
    _configure_logging(settings.state_dir / "logs" / "host.log" if machine else None)
    plural_host = await build_host(settings)
    invite = plural_host.invites.create(Role.PARTICIPANT, settings.invite_ttl_s)
    if machine:
        print(ready_line(plural_host.room, invite.link, plural_host.host_link), flush=True)
    elif console.is_terminal:
        console.print(
            Panel(
                f"[bold]Guest link[/bold] (one-time)\n{invite.link}\n\n"
                f"[bold]Host link[/bold]\n{plural_host.host_link}",
                title=f"room {plural_host.room}",
            )
        )
    else:
        print(plain_links(plural_host.room, invite.link, plural_host.host_link), flush=True)
    try:
        if machine:
            await _serve_until_stdin_closes(plural_host, settings)
        else:
            await plural_host.serve()
    finally:
        await plural_host.close()


async def _serve_until_stdin_closes(plural_host: Host, settings: HostSettings) -> None:
    serving = asyncio.create_task(plural_host.serve())
    watching = asyncio.create_task(_control_until_stdin_closes(plural_host, settings))
    done, pending = await asyncio.wait({serving, watching}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    if serving in done:
        serving.result()


def _write_reply(message: dict[str, object]) -> None:
    print(json.dumps(message), flush=True)


async def _control_until_stdin_closes(plural_host: Host, settings: HostSettings) -> None:
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=2 * MAX_LINE_BYTES)
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    control = Control(plural_host, settings, _write_reply)
    await read_lines(reader, control.handle)


@app.command()
def relay(
    bind: Annotated[str, typer.Option(help="Bind address.", envvar="PLURAL_RELAY_BIND")] = (
        "127.0.0.1"
    ),
    port: Annotated[int, typer.Option(help="Port.", envvar="PORT")] = 8787,
    proxy_hops: Annotated[
        int,
        typer.Option(
            min=0,
            help="Proxies in front of the relay, to tell guests apart. 0 when it is exposed.",
            envvar="PLURAL_RELAY_PROXY_HOPS",
        ),
    ] = 0,
    max_rooms: Annotated[
        int, typer.Option(min=1, help="Rooms at once.", envvar="PLURAL_RELAY_MAX_ROOMS")
    ] = DEFAULT_LIMITS.max_rooms,
    rooms_per_peer: Annotated[
        int,
        typer.Option(
            min=1, help="Rooms one address may host.", envvar="PLURAL_RELAY_ROOMS_PER_PEER"
        ),
    ] = DEFAULT_LIMITS.max_rooms_per_peer,
    guests_per_peer: Annotated[
        int,
        typer.Option(
            min=1, help="Guests one address may bring.", envvar="PLURAL_RELAY_GUESTS_PER_PEER"
        ),
    ] = DEFAULT_LIMITS.max_guests_per_peer,
) -> None:
    limits = RelayLimits(
        max_rooms=max_rooms,
        max_rooms_per_peer=rooms_per_peer,
        max_guests_per_peer=guests_per_peer,
    )
    uvicorn.run(
        create_app(limits, proxy_hops=proxy_hops),
        host=bind,
        port=port,
        log_level="info",
        ws_max_size=4 * 1024 * 1024,
        proxy_headers=False,
    )


@app.command()
def doctor(
    workspace: Annotated[Path, typer.Option(help="Project directory to check.")] = Path("."),
) -> None:
    settings = HostSettings(workspace=workspace)
    provider_ok, provider_detail = _provider_check(settings)
    checks = [
        ("python >= 3.12", sys.version_info >= (3, 12), sys.version.split()[0]),
        ("workspace exists", settings.workspace.is_dir(), str(settings.workspace.resolve())),
        ("data dir", _writable(settings.state_dir), str(settings.state_dir)),
        ("provider", provider_ok, provider_detail),
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


def _provider_check(settings: HostSettings) -> tuple[bool, str]:
    try:
        build_provider(settings, resolve_api_key(settings, os.environ))
    except ConfigError as error:
        return False, str(error)
    return True, settings.agent_label()


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
