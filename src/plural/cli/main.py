import asyncio
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Annotated

import structlog
import typer
import uvicorn
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from plural import __version__
from plural.host.bootstrap import ConfigError, build_host, build_provider, resolve_api_key
from plural.host.config import HostSettings
from plural.protocol.envelope import PROTOCOL_VERSION
from plural.protocol.models import PromptMode, Role
from plural.relay.app import create_app
from plural.storage.jsonl_export import export_jsonl
from plural.storage.sqlite_store import SqliteEventStore

app = typer.Typer(name="plural-host", no_args_is_help=True, add_completion=False)
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
    prompts: Annotated[
        PromptMode | None,
        typer.Option(help="open: participants prompt directly; review: the host approves them."),
    ] = None,
    machine: Annotated[
        bool,
        typer.Option("--json", help="Print one JSON line when ready and log to a file."),
    ] = False,
) -> None:
    settings = HostSettings(
        workspace=workspace,
        bind_host=bind,
        port=port,
        relay_url=relay,
        public_url=public_url,
        room=room,
        host_name=name,
        prompt_mode=prompts,
    )
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


async def _host(settings: HostSettings, *, machine: bool) -> None:
    _configure_logging(settings.state_dir / "logs" / "host.log" if machine else None)
    plural_host = await build_host(settings)
    invite = plural_host.invites.create(Role.PARTICIPANT, settings.invite_ttl_s)
    if machine:
        print(ready_line(plural_host.room, invite.link, plural_host.host_link), flush=True)
    else:
        console.print(
            Panel(
                f"[bold]Guest link[/bold] (one-time)\n{invite.link}\n\n"
                f"[bold]Host link[/bold]\n{plural_host.host_link}",
                title=f"room {plural_host.room}",
            )
        )
    try:
        await plural_host.serve()
    finally:
        await plural_host.close()


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
    return True, settings.provider + (f" · {settings.model}" if settings.model else "")


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
