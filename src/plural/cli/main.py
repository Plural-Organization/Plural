import asyncio
import getpass
import json
import os
import sqlite3
import sys
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import structlog
import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from plural import __version__
from plural.cli.account import login, logout, whoami
from plural.cli.agent import agent_app
from plural.cli.format import ago
from plural.cli.stop import stop
from plural.cli.team import ls, team_app
from plural.host.config import DEFAULT_MCP_URL, DEFAULT_RELAY_URL, HostSettings
from plural.host.team import TeamStore
from plural.protocol.envelope import PROTOCOL_VERSION
from plural.protocol.models import AdmissionMode, PromptMode
from plural.relay.directory import TeamLimits
from plural.relay.limits import RelayLimits
from plural.storage.jsonl_export import export_jsonl
from plural.storage.sessions import delete_session, list_sessions, read_session, session_path
from plural.storage.sqlite_store import SqliteEventStore

if TYPE_CHECKING:
    from plural.host.bootstrap import Host

app = typer.Typer(name="plural-host", no_args_is_help=True, add_completion=False)
app.add_typer(team_app, name="team")
app.add_typer(agent_app, name="agent")
app.command(name="ls")(ls)
app.command(name="login")(login)
app.command(name="stop")(stop)
app.command(name="logout")(logout)
app.command(name="whoami")(whoami)
console = Console()
DEFAULT_LIMITS = RelayLimits()
DEFAULT_TEAM_LIMITS = TeamLimits()


@app.command()
def host(
    workspace: Annotated[
        Path | None, typer.Option(help="Project directory the agent works in.")
    ] = None,
    bind: Annotated[str | None, typer.Option(help="Address for direct mode.")] = None,
    port: Annotated[int | None, typer.Option(help="Port for direct mode.")] = None,
    relay: Annotated[
        str | None,
        typer.Option(help="Relay URL. Default: your team's relay, else the Plural relay."),
    ] = None,
    local: Annotated[
        bool, typer.Option("--local", help="Stay on this machine: no relay, direct mode.")
    ] = False,
    public_url: Annotated[str | None, typer.Option(help="Public ws(s) URL for links.")] = None,
    mcp_url: Annotated[
        str | None,
        typer.Option(help="MCP gateway that lets Claude, ChatGPT or Grok send chats here."),
    ] = None,
    room: Annotated[str | None, typer.Option(help="Resume an existing room.")] = None,
    title: Annotated[str | None, typer.Option(help="Name of this session.")] = None,
    import_from: Annotated[
        str | None,
        typer.Option(
            "--import",
            help="Start from a session of another agent: claude, or claude:<id start>.",
        ),
    ] = None,
    name: Annotated[str | None, typer.Option(help="Host display name.")] = None,
    prompts: Annotated[
        PromptMode | None,
        typer.Option(help="open: participants prompt directly; review: the host approves them."),
    ] = None,
    admission: Annotated[
        AdmissionMode | None,
        typer.Option(help="approve: the host lets in whoever uses the room link; open: anyone."),
    ] = None,
    team: Annotated[
        bool,
        typer.Option(
            "--team",
            help="Show this session to your team. Needs --relay, --public-url or a tunnel.",
        ),
    ] = False,
    team_id: Annotated[
        str | None,
        typer.Option(
            "--team-id",
            help="Show this session to this one of your teams (implies --team).",
            envvar="PLURAL_TEAM_ID",
        ),
    ] = None,
    machine: Annotated[
        bool,
        typer.Option(
            "--json", help="Print one JSON line when ready, log to a file, quit when stdin closes."
        ),
    ] = False,
) -> None:
    given: dict[str, Any] = {
        "team": True if team or team_id else None,
        "team_id": team_id,
        "workspace": workspace,
        "bind_host": bind,
        "port": port,
        "relay_url": relay,
        "public_url": public_url,
        "mcp_url": mcp_url,
        "room": room,
        "title": title,
        "import_from": import_from,
        "host_name": name,
        "prompt_mode": prompts,
        "admission": admission,
    }
    options = {key: value for key, value in given.items() if value is not None}
    if room is not None and workspace is None and "PLURAL_WORKSPACE" not in os.environ:
        options["workspace"] = _saved_workspace(room)
    if name is None and "PLURAL_HOST_NAME" not in os.environ:
        options["host_name"] = getpass.getuser()
    settings = HostSettings(**options)
    if local:
        settings = settings.model_copy(update={"relay_url": None, "mcp_url": None})
    else:
        if settings.mcp_url is None:
            settings = settings.model_copy(update={"mcp_url": DEFAULT_MCP_URL})
        if _wants_relay(settings):
            settings = settings.model_copy(update={"relay_url": _default_relay(settings)})
    from plural.host.providers import ConfigError
    from plural.host.team_presence import PresenceUnavailable

    try:
        asyncio.run(_host(settings, machine=machine))
    except (ConfigError, PresenceUnavailable) as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(1) from error


def _wants_relay(settings: HostSettings) -> bool:
    """A host with no address of its own goes through a relay; --bind and --public-url opt out."""
    direct = settings.public_url or "bind_host" in settings.model_fields_set
    return settings.relay_url is None and not direct


def _default_relay(settings: HostSettings) -> str:
    profile = TeamStore(settings.state_dir, settings.team_id).load() if settings.team else None
    return profile.relay if profile is not None else DEFAULT_RELAY_URL


def _saved_workspace(room: str) -> Path:
    data_dir = HostSettings().state_dir
    try:
        path = session_path(data_dir, room)
    except ValueError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(2) from error
    info = read_session(path) if path.exists() else None
    if info is None:
        console.print(
            f"[red]There is no session {room}. List them with plural-host sessions.[/red]"
        )
        raise typer.Exit(1)
    if info.workspace is None:
        return Path.cwd()
    folder = Path(info.workspace)
    if not folder.is_dir():
        console.print(
            f"[red]The folder of this session is gone: {folder}. "
            "Pass --workspace to continue it somewhere else.[/red]"
        )
        raise typer.Exit(1)
    return folder


def ready_line(room: str, guest_link: str, host_link: str, import_url: str | None = None) -> str:
    return json.dumps(
        {
            "type": "ready",
            "room": room,
            "guest_link": guest_link,
            "host_link": host_link,
            "import_url": import_url,
            "version": __version__,
            "protocol": PROTOCOL_VERSION,
        }
    )


def plain_links(room: str, guest_link: str, host_link: str) -> str:
    return "\n".join(
        (
            f"room {room}",
            f"room link (the host lets people in): {guest_link}",
            f"host link: {host_link}",
        )
    )


async def _host(settings: HostSettings, *, machine: bool) -> None:
    from plural.host.bootstrap import build_host
    from plural.host.team_presence import TeamPresence, ensure_ready

    _configure_logging(settings.state_dir / "logs" / "host.log" if machine else None)
    if settings.team:
        ensure_ready(settings, TeamStore(settings.state_dir, settings.team_id))
    plural_host = await build_host(settings)
    room_link = plural_host.room_link.link
    if machine:
        print(
            ready_line(plural_host.room, room_link, plural_host.host_link, plural_host.import_url),
            flush=True,
        )
    elif console.is_terminal:
        console.print(
            Panel(
                f"[bold]Room link[/bold] (the host lets people in)\n{room_link}\n\n"
                f"[bold]Host link[/bold]\n{plural_host.host_link}",
                title=f"room {plural_host.room}",
            )
        )
    else:
        print(plain_links(plural_host.room, room_link, plural_host.host_link), flush=True)
    presence = (
        asyncio.create_task(
            TeamPresence(
                plural_host, settings, TeamStore(settings.state_dir, settings.team_id)
            ).run()
        )
        if settings.team
        else None
    )
    try:
        if machine:
            await _serve_until_stdin_closes(plural_host, settings)
        else:
            await plural_host.serve()
    finally:
        if presence is not None:
            presence.cancel()
            with suppress(asyncio.CancelledError):
                await presence
        await plural_host.close()


async def _serve_until_stdin_closes(plural_host: "Host", settings: HostSettings) -> None:
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


async def _control_until_stdin_closes(plural_host: "Host", settings: HostSettings) -> None:
    from plural.host.control import MAX_LINE_BYTES, Control, read_lines

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
    teams: Annotated[
        Path | None,
        typer.Option(
            help="SQLite file for the team directory. Without it the relay serves no teams.",
            envvar="PLURAL_RELAY_TEAMS",
        ),
    ] = None,
    teams_per_owner: Annotated[
        int,
        typer.Option(
            min=1,
            help="Teams one key may own. A relay run for one person can raise it.",
            envvar="PLURAL_RELAY_TEAMS_PER_OWNER",
        ),
    ] = DEFAULT_TEAM_LIMITS.max_teams_per_owner,
    clients_only: Annotated[
        bool,
        typer.Option(
            "--clients-only",
            help="Refuse anything that does not call itself a Plural client (or a --web-origin).",
            envvar="PLURAL_RELAY_CLIENTS_ONLY",
        ),
    ] = False,
    web_origins: Annotated[
        str,
        typer.Option(
            "--web-origin",
            help="Comma-separated origins of web clients let in by --clients-only.",
            envvar="PLURAL_RELAY_WEB_ORIGINS",
        ),
    ] = "",
    accounts_url: Annotated[
        str,
        typer.Option(
            "--accounts-url",
            help="Accounts service whose certificates hosts may open rooms with. The relay "
            "logs what it finds and refuses no one.",
            envvar="PLURAL_RELAY_ACCOUNTS_URL",
        ),
    ] = "",
) -> None:
    import uvicorn

    from plural.relay.app import create_app

    limits = RelayLimits(
        max_rooms=max_rooms,
        max_rooms_per_peer=rooms_per_peer,
        max_guests_per_peer=guests_per_peer,
    )
    uvicorn.run(
        create_app(
            limits,
            proxy_hops=proxy_hops,
            teams=teams,
            team_limits=TeamLimits(max_teams_per_owner=teams_per_owner),
            clients_only=clients_only,
            web_origins=[item.strip() for item in web_origins.split(",") if item.strip()],
            accounts_url=accounts_url.strip() or None,
        ),
        host=bind,
        port=port,
        log_level="info",
        ws_max_size=4 * 1024 * 1024,
        proxy_headers=False,
    )


@app.command()
def daemon(
    port: Annotated[
        int, typer.Option(min=1, max=65535, help="Loopback port.", envvar="PLURAL_DAEMON_PORT")
    ] = 47831,
    origins: Annotated[
        str,
        typer.Option(
            "--origin",
            help="Comma-separated web client origins that may use the daemon.",
            envvar="PLURAL_DAEMON_ORIGINS",
        ),
    ] = "https://plrl.host,https://www.plrl.host",
) -> None:
    """Let the Plural web client start rooms on this computer, in folders you choose."""
    import uvicorn

    from plural.daemon.app import create_app
    from plural.host.account import AccountError, AccountStore
    from plural.security.accounts_key import AccountsKey

    settings = HostSettings()
    store = AccountStore(settings.state_dir)
    try:
        linked = store.load()
    except AccountError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(1) from error
    if linked is None:
        console.print("[red]This computer is not linked to an account. Run `plural login`.[/red]")
        raise typer.Exit(1)
    from plural.daemon.port import PortState, port_state

    taken = port_state(port)
    if taken is PortState.DAEMON:
        console.print(
            f"Plural daemon is already running on http://127.0.0.1:{port}. Nothing to do."
        )
        return
    if taken is PortState.BUSY:
        console.print(
            f"[red]Port {port} is used by something else.[/red] "
            "Stop it, or pick another port with `plural daemon --port`."
        )
        raise typer.Exit(1)
    console.print(f"Plural daemon for {linked.email} on http://127.0.0.1:{port}. Ctrl+C stops it.")
    uvicorn.run(
        create_app(
            store,
            AccountsKey(linked.accounts),
            port=port,
            origins=tuple(item.strip() for item in origins.split(",") if item.strip()),
        ),
        host="127.0.0.1",
        port=port,
        log_level="warning",
        proxy_headers=False,
    )


@app.command()
def sessions(
    workspace: Annotated[
        Path | None, typer.Option(help="Only sessions that worked in this folder.")
    ] = None,
    limit: Annotated[int, typer.Option(min=1, help="How many to show.")] = 50,
    as_json: Annotated[bool, typer.Option("--json", help="One JSON array, for scripts.")] = False,
) -> None:
    found = list_sessions(HostSettings().state_dir, workspace=workspace)[:limit]
    if as_json:
        print(json.dumps([json.loads(info.model_dump_json()) for info in found]), flush=True)
        return
    if not found:
        console.print("No sessions yet.")
        return
    for info in found:
        where = f"[cyan]team {escape(info.team)}[/cyan]  " if info.team else ""
        console.print(
            f"[bold]{escape(info.title)}[/bold]  {where}"
            f"[dim]{info.prompts} prompts · {ago(info.updated_at)}[/dim]",
            soft_wrap=True,
        )
        console.print(f"  [dim]{info.room}  {escape(info.workspace or '')}[/dim]", soft_wrap=True)


@app.command()
def rm(
    room: Annotated[str, typer.Argument(help="Session id.")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask.")] = False,
) -> None:
    data_dir = HostSettings().state_dir
    try:
        info = read_session(session_path(data_dir, room))
    except ValueError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(2) from error
    if info is None:
        console.print(f"[red]There is no session {room}.[/red]")
        raise typer.Exit(1)
    if not yes and not typer.confirm(f"Delete “{info.title}” ({room}) for good?"):
        raise typer.Exit(1)
    delete_session(data_dir, room)
    console.print(f"Deleted {room}.")


@app.command()
def fork(
    room: Annotated[str, typer.Argument(help="Session id to copy.")],
    title: Annotated[str | None, typer.Option(help="Name of the new session.")] = None,
    before: Annotated[
        str | None, typer.Option(help="Copy only what came before this prompt id.")
    ] = None,
) -> None:
    """Copy a session into a new one, to try another way from the same point."""
    from datetime import UTC, datetime

    from plural.host.system import UlidGenerator
    from plural.storage.sessions import fork_session, prompt_seq

    data_dir = HostSettings().state_dir
    try:
        before_seq = None if before is None else prompt_seq(data_dir, room, before)
        if before is not None and before_seq is None:
            raise ValueError(f"there is no prompt {before} in {room}")
        new_room = UlidGenerator().new("r_")
        fork_session(
            data_dir, room, new_room, before_seq=before_seq, title=title, now=datetime.now(UTC)
        )
    except (ValueError, OSError, sqlite3.Error) as error:
        console.print(f"[red]{escape(str(error))}[/red]")
        raise typer.Exit(1) from error
    console.print(f"Forked {room} into {new_room}. Continue it with: plural -r {new_room}")


plugins_app = typer.Typer(help="Install and list the host's plugins.", no_args_is_help=True)
app.add_typer(plugins_app, name="plugins")


@plugins_app.command("install")
def plugins_install(
    source: Annotated[str, typer.Argument(help="A git URL, a plugin folder or a .py file.")],
    name: Annotated[str | None, typer.Option(help="Install under this name.")] = None,
) -> None:
    """Install a plugin. It runs inside the host with your permissions: install only code you
    trust. A running host picks it up with /plugins reload."""
    from plural.host.plugin_install import install
    from plural.host.plugins import PluginError

    try:
        target = install(source, HostSettings().state_dir / "plugins", name=name)
    except PluginError as error:
        console.print(f"[red]{escape(str(error))}[/red]")
        raise typer.Exit(1) from error
    console.print(f"Installed {escape(str(target))}. In a running session: /plugins reload")


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
    from plural.host.providers import ConfigError, build_provider, resolve_api_key

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
        structlog.contextvars.merge_contextvars,
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
