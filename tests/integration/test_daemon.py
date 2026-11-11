import asyncio
import json
import sys
import urllib.error
import urllib.request
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tests.e2e.support import free_port

from plural.agent_setup import AgentSetup
from plural.daemon.app import create_app
from plural.daemon.folders import FolderPickerUnavailable, Folders
from plural.daemon.rooms import Rooms
from plural.daemon.terminal import TerminalUnavailable
from plural.host.account import AccountStore, Entitlement
from plural.protocol.entitlement import EntitlementClaims
from plural.protocol.ticket import TicketClaims
from plural.security.accounts_key import AccountsKey
from plural.security.entitlement import EntitlementVerifier
from plural.security.tokens import b64encode

WEB = "https://web.example.com"

FAKE_HOST = """
import json, os, sys
if "break_it" in " ".join(sys.argv):
    sys.stderr.write("no provider configured")
    sys.exit(3)
room = "r_" + sys.argv[sys.argv.index("--workspace") + 1][-6:].replace("/", "")
print(json.dumps({
    "type": "ready", "room": room, "guest_link": "wss://relay.example/r_x",
    "host_link": "wss://relay.example/r_x?token=t", "import_url": None,
    "version": "0", "protocol": 1,
}), flush=True)
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, "argv.jsonl"), "a") as file:
    file.write(json.dumps(sys.argv[1:]) + "\\n")
log = os.path.join(here, "received.jsonl")
for line in sys.stdin:
    request = json.loads(line)
    with open(log, "a") as file:
        file.write(line)
    config = request.get("config", {})
    if config.get("model") == "refuse":
        reply = {"type": "result", "id": request["id"], "ok": False, "error": "not installed"}
    else:
        label = f"{config.get('provider_name')} · {config.get('model') or 'default'}"
        reply = {"type": "result", "id": request["id"], "ok": True, "agent": label}
    print(json.dumps(reply), flush=True)
"""


def sign(key: Ed25519PrivateKey, claims: EntitlementClaims | TicketClaims) -> str:
    body = claims.model_dump_json().encode()
    return f"{b64encode(body)}.{b64encode(key.sign(body))}"


class Picker:
    def __init__(self) -> None:
        self.answer: Path | None = None
        self.unavailable = False

    async def pick(self) -> Path | None:
        if self.unavailable:
            raise FolderPickerUnavailable("no dialog here")
        return self.answer


class Terminal:
    def __init__(self) -> None:
        self.ran: list[str] = []
        self.unavailable = False

    async def run(self, command: str) -> None:
        if self.unavailable:
            raise TerminalUnavailable("no terminal here")
        self.ran.append(command)


@dataclass(slots=True)
class Daemon:
    url: str
    port: int
    accounts: Ed25519PrivateKey
    picker: Picker
    now: datetime
    agent: AgentSetup
    terminal: Terminal
    received: Path

    def host_arguments(self) -> list[list[str]]:
        """The arguments each host was started with, oldest first."""
        argv = self.received.parent / "argv.jsonl"
        return [json.loads(line) for line in argv.read_text().splitlines()] if argv.exists() else []

    def sent_to_host(self) -> list[dict[str, Any]]:
        """What the daemon wrote down the host's control channel, oldest first."""
        if not self.received.exists():
            return []
        return [json.loads(line) for line in self.received.read_text().splitlines()]

    def ticket(self, account: str = "a_me", *, nonce: str | None = None, expires: int = 60) -> str:
        nonce = nonce or f"n{len(str(id(object())))}{asyncio.get_event_loop().time()}"
        claims = TicketClaims(
            account=account, nonce=nonce, iat=self.now, exp=self.now + timedelta(seconds=expires)
        )
        return sign(self.accounts, claims)

    async def call(
        self,
        method: str,
        path: str,
        *,
        origin: str | None = WEB,
        host: str | None = None,
        ticket: str | None = None,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any], dict[str, str]]:
        def run() -> tuple[int, dict[str, Any], dict[str, str]]:
            sent = {"Host": host or f"127.0.0.1:{self.port}", **(headers or {})}
            if origin is not None:
                sent["Origin"] = origin
            if ticket is not None:
                sent["Authorization"] = f"Bearer {ticket}"
            data = json.dumps(body).encode() if body is not None else None
            if data is not None:
                sent["Content-Type"] = "application/json"
            request = urllib.request.Request(
                self.url + path, data=data, method=method, headers=sent
            )
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    raw = response.read()
                    return (
                        response.status,
                        json.loads(raw) if raw else {},
                        {k.lower(): v for k, v in response.headers.items()},
                    )
            except urllib.error.HTTPError as error:
                raw = error.read()
                return (
                    error.code,
                    json.loads(raw) if raw else {},
                    {k.lower(): v for k, v in error.headers.items()},
                )

        return await asyncio.to_thread(run)


@asynccontextmanager
async def running_daemon(
    tmp_path: Path, *, linked: bool = True, limit: int = 5
) -> AsyncGenerator[Daemon]:
    accounts = Ed25519PrivateKey.generate()
    now = datetime.now(UTC)
    store = AccountStore(tmp_path / "state")
    if linked:
        certificate = sign(
            accounts,
            EntitlementClaims(account="a_me", key="hostkey", iat=now, exp=now + timedelta(days=7)),
        )
        store.save(
            Entitlement(
                accounts="https://accounts.example",
                email="alia@example.com",
                certificate=certificate,
                expires_at=now + timedelta(days=7),
            )
        )
    script = tmp_path / "fake_host.py"
    script.write_text(FAKE_HOST)
    picker = Picker()
    agent = AgentSetup(tmp_path / "state", environ={})
    terminal = Terminal()
    key = AccountsKey(
        "https://accounts.example", fetch=lambda _: EntitlementVerifier(accounts.public_key())
    )
    port = free_port()
    app = create_app(
        store,
        key,
        port=port,
        origins=(WEB + "/",),
        folders=Folders(picker),
        rooms=Rooms([sys.executable, str(script)], limit=limit),
        agent=agent,
        terminal=terminal,
        clock=lambda: now,
    )
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    async with asyncio.timeout(10):
        while not (server.started and key.ready):
            await asyncio.sleep(0.01)
    try:
        yield Daemon(
            f"http://127.0.0.1:{port}",
            port,
            accounts,
            picker,
            now,
            agent,
            terminal,
            tmp_path / "received.jsonl",
        )
    finally:
        server.should_exit = True
        await task


async def test_anyone_may_ask_whether_a_daemon_is_here_and_nothing_else(tmp_path: Path) -> None:
    async with running_daemon(tmp_path) as daemon:
        status, body, _ = await daemon.call("GET", "/v1/status", origin=None)
        assert (status, body["daemon"], body["linked"]) == (200, True, True)
        status, body, _ = await daemon.call("GET", "/v1/account", origin=None)
        assert (status, body["error"]["code"]) == (403, "no_origin")


async def test_a_page_on_another_origin_or_a_rebound_name_is_refused(tmp_path: Path) -> None:
    async with running_daemon(tmp_path) as daemon:
        status, body, _ = await daemon.call("GET", "/v1/status", origin="https://evil.example")
        assert (status, body["error"]["code"]) == (403, "bad_origin")
        status, body, _ = await daemon.call("GET", "/v1/status", host=f"evil.example:{daemon.port}")
        assert (status, body["error"]["code"]) == (403, "bad_host")
        status, _, _ = await daemon.call("GET", "/v1/status", host=f"localhost:{daemon.port}")
        assert status == 200


async def test_the_web_client_gets_cors_headers_and_a_preflight_answer(tmp_path: Path) -> None:
    async with running_daemon(tmp_path) as daemon:
        status, _, headers = await daemon.call(
            "OPTIONS",
            "/v1/rooms",
            headers={
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert status == 204
        assert headers["access-control-allow-origin"] == WEB
        assert "authorization" in headers["access-control-allow-headers"]
        assert headers["access-control-allow-private-network"] == "true"
        _, _, answer = await daemon.call("GET", "/v1/status")
        assert answer["access-control-allow-origin"] == WEB


async def test_only_a_fresh_ticket_for_this_computers_account_gets_in(tmp_path: Path) -> None:
    async with running_daemon(tmp_path) as daemon:
        ticket = daemon.ticket(nonce="once")
        status, body, _ = await daemon.call("GET", "/v1/account", ticket=ticket)
        assert (status, body["email"]) == (200, "alia@example.com")
        status, body, _ = await daemon.call("GET", "/v1/account", ticket=ticket)
        assert (status, body["error"]["code"]) == (401, "ticket_used")
        status, body, _ = await daemon.call("GET", "/v1/account")
        assert (status, body["error"]["code"]) == (401, "no_ticket")
        status, body, _ = await daemon.call("GET", "/v1/account", ticket=daemon.ticket(expires=-1))
        assert (status, body["error"]["code"], body["error"]["reason"]) == (
            401,
            "bad_ticket",
            "expired",
        )
        forged = sign(
            Ed25519PrivateKey.generate(),
            TicketClaims(
                account="a_me", nonce="x", iat=daemon.now, exp=daemon.now + timedelta(seconds=60)
            ),
        )
        status, body, _ = await daemon.call("GET", "/v1/account", ticket=forged)
        assert (status, body["error"]["code"], body["error"]["reason"]) == (
            401,
            "bad_ticket",
            "forged",
        )
        status, body, _ = await daemon.call("GET", "/v1/account", ticket=daemon.ticket("a_other"))
        assert (status, body["error"]["code"], body["error"]["linked_email"]) == (
            403,
            "wrong_account",
            "alia@example.com",
        )


async def test_a_ticket_for_the_team_directory_does_not_open_the_daemon(tmp_path: Path) -> None:
    async with running_daemon(tmp_path) as daemon:
        claims = TicketClaims.model_validate(
            {
                "aud": "teams",
                "account": "a_me",
                "nonce": "teams-1",
                "iat": daemon.now,
                "exp": daemon.now + timedelta(seconds=60),
            }
        )
        status, body, _ = await daemon.call(
            "GET", "/v1/account", ticket=sign(daemon.accounts, claims)
        )
        assert (status, body["error"]["code"], body["error"]["reason"]) == (
            401,
            "bad_ticket",
            "wrong_audience",
        )


async def test_a_certificate_is_not_a_ticket(tmp_path: Path) -> None:
    async with running_daemon(tmp_path) as daemon:
        certificate = sign(
            daemon.accounts,
            EntitlementClaims(
                account="a_me", key="k", iat=daemon.now, exp=daemon.now + timedelta(days=7)
            ),
        )
        status, body, _ = await daemon.call("GET", "/v1/account", ticket=certificate)
        assert (status, body["error"]["code"]) == (401, "bad_ticket")


async def test_an_unlinked_computer_says_so(tmp_path: Path) -> None:
    async with running_daemon(tmp_path, linked=False) as daemon:
        _, body, _ = await daemon.call("GET", "/v1/status")
        assert body["linked"] is False
        status, body, _ = await daemon.call("GET", "/v1/account", ticket=daemon.ticket())
        assert (status, body["error"]["code"]) == (409, "not_linked")


async def test_a_room_starts_in_a_folder_the_person_picked_and_stops_on_request(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    async with running_daemon(tmp_path) as daemon:
        daemon.picker.answer = project
        status, picked, _ = await daemon.call(
            "POST", "/v1/folders/pick", ticket=daemon.ticket(nonce="a")
        )
        assert (status, picked["name"]) == (200, "project")
        status, room, _ = await daemon.call(
            "POST",
            "/v1/rooms",
            ticket=daemon.ticket(nonce="b"),
            body={"folder": picked["folder"], "title": "Spike"},
        )
        assert status == 201, room
        assert room["host_link"].startswith("wss://relay.example/")
        assert (room["folder"], room["title"]) == ("project", "Spike")
        _, listing, _ = await daemon.call("GET", "/v1/rooms", ticket=daemon.ticket(nonce="c"))
        assert [item["room"] for item in listing["rooms"]] == [room["room"]]
        status, _, _ = await daemon.call(
            "DELETE", f"/v1/rooms/{room['room']}", ticket=daemon.ticket(nonce="d")
        )
        assert status == 204
        async with asyncio.timeout(10):
            while True:
                _, listing, _ = await daemon.call(
                    "GET",
                    "/v1/rooms",
                    ticket=daemon.ticket(nonce=f"e{asyncio.get_event_loop().time()}"),
                )
                if not listing["rooms"]:
                    break
                await asyncio.sleep(0.05)
        status, body, _ = await daemon.call(
            "DELETE", "/v1/rooms/r_none", ticket=daemon.ticket(nonce="f")
        )
        assert (status, body["error"]["code"]) == (404, "no_room")


async def test_a_path_from_the_browser_is_not_a_folder(tmp_path: Path) -> None:
    async with running_daemon(tmp_path) as daemon:
        for named in (str(tmp_path), "/etc", "f_unknown"):
            status, body, _ = await daemon.call(
                "POST", "/v1/rooms", ticket=daemon.ticket(nonce=f"p{named}"), body={"folder": named}
            )
            assert (status, body["error"]["code"]) == (400, "unknown_folder")


async def test_closing_the_dialog_and_a_missing_dialog_are_told_apart(tmp_path: Path) -> None:
    async with running_daemon(tmp_path) as daemon:
        status, body, _ = await daemon.call(
            "POST", "/v1/folders/pick", ticket=daemon.ticket(nonce="a")
        )
        assert (status, body["folder"]) == (200, None)
        daemon.picker.unavailable = True
        status, body, _ = await daemon.call(
            "POST", "/v1/folders/pick", ticket=daemon.ticket(nonce="b")
        )
        assert (status, body["error"]["code"]) == (409, "no_folder_dialog")


async def test_a_host_that_fails_to_start_says_why_and_the_room_limit_holds(tmp_path: Path) -> None:
    good = tmp_path / "good"
    bad = tmp_path / "break_it"
    good.mkdir()
    bad.mkdir()
    async with running_daemon(tmp_path, limit=1) as daemon:
        daemon.picker.answer = bad
        _, failing, _ = await daemon.call(
            "POST", "/v1/folders/pick", ticket=daemon.ticket(nonce="a")
        )
        status, body, _ = await daemon.call(
            "POST", "/v1/rooms", ticket=daemon.ticket(nonce="b"), body={"folder": failing["folder"]}
        )
        assert (status, body["error"]["code"]) == (409, "host_failed")
        assert "no provider configured" in body["error"]["message"]
        daemon.picker.answer = good
        _, ok, _ = await daemon.call("POST", "/v1/folders/pick", ticket=daemon.ticket(nonce="c"))
        assert (
            await daemon.call(
                "POST", "/v1/rooms", ticket=daemon.ticket(nonce="d"), body={"folder": ok["folder"]}
            )
        )[0] == 201
        status, body, _ = await daemon.call(
            "POST", "/v1/rooms", ticket=daemon.ticket(nonce="e"), body={"folder": ok["folder"]}
        )
        assert (status, body["error"]["code"]) == (409, "too_many_rooms")


@pytest.mark.parametrize("path", ["/v1/folders/pick", "/v1/rooms"])
async def test_every_action_needs_a_ticket(tmp_path: Path, path: str) -> None:
    async with running_daemon(tmp_path) as daemon:
        status, body, _ = await daemon.call("POST", path, body={"folder": "x"})
        assert (status, body["error"]["code"]) == (401, "no_ticket")


# --- the agent ---------------------------------------------------------------------------------

KEY = "sk-ant-api03-0123456789abcdefghijklmnop"


async def picked(daemon: Daemon, folder: Path, nonce: str) -> str:
    await asyncio.to_thread(folder.mkdir, exist_ok=True)
    daemon.picker.answer = folder
    _, body, _ = await daemon.call("POST", "/v1/folders/pick", ticket=daemon.ticket(nonce=nonce))
    return str(body["folder"])


async def test_every_agent_call_needs_a_ticket(tmp_path: Path) -> None:
    calls = [
        ("GET", "/v1/agent", None),
        ("PUT", "/v1/agent", {"agent": {"preset": "demo"}}),
        ("PUT", "/v1/agent/key", {"preset": "anthropic", "key": KEY}),
        ("DELETE", "/v1/agent/key/anthropic", None),
        ("POST", "/v1/agent/test", {"choice": {"preset": "demo"}}),
        ("POST", "/v1/agent/install", {"tool": "claude"}),
        ("POST", "/v1/agent/sign-in", {"tool": "claude"}),
        ("PUT", "/v1/rooms/r_x/agent", {"agent": {"preset": "demo"}}),
    ]
    async with running_daemon(tmp_path) as daemon:
        for method, path, body in calls:
            status, answer, _ = await daemon.call(method, path, body=body)
            assert (status, answer["error"]["code"]) == (401, "no_ticket"), (method, path)
            status, answer, _ = await daemon.call(method, path, body=body, origin=None)
            assert (status, answer["error"]["code"]) == (403, "no_origin"), (method, path)
    assert daemon.terminal.ran == []


async def test_the_preflight_allows_the_methods_the_agent_screen_uses(tmp_path: Path) -> None:
    async with running_daemon(tmp_path) as daemon:
        _, _, headers = await daemon.call(
            "OPTIONS",
            "/v1/agent",
            headers={"Access-Control-Request-Method": "PUT"},
        )
        assert "PUT" in headers["access-control-allow-methods"]


async def test_a_key_goes_in_and_the_catalog_only_says_it_is_there(tmp_path: Path) -> None:
    async with running_daemon(tmp_path) as daemon:
        status, answer, _ = await daemon.call(
            "PUT",
            "/v1/agent/key",
            ticket=daemon.ticket(nonce="k"),
            body={"preset": "anthropic", "key": KEY},
        )
        assert (status, answer) == (204, {})
        status, catalog, _ = await daemon.call("GET", "/v1/agent", ticket=daemon.ticket(nonce="c"))
        assert status == 200
        assert KEY not in json.dumps(catalog)
        anthropic = next(entry for entry in catalog["presets"] if entry["id"] == "anthropic")
        assert (anthropic["key"]["set"], anthropic["key"]["source"]) == (True, "saved")
        assert {entry["id"] for entry in catalog["presets"]} >= {
            "claude_code",
            "codex_cli",
            "ollama",
        }
        status, answer, _ = await daemon.call(
            "PUT",
            "/v1/agent/key",
            ticket=daemon.ticket(nonce="bad"),
            body={"preset": "anthropic", "key": "two words"},
        )
        assert (status, answer["error"]["code"]) == (400, "bad_key")
        status, _, _ = await daemon.call(
            "DELETE", "/v1/agent/key/anthropic", ticket=daemon.ticket(nonce="d")
        )
        assert status == 204
        assert daemon.agent.store.key("anthropic") is None


async def test_a_room_runs_the_agent_the_page_chose_with_a_key_the_page_never_sent(
    tmp_path: Path,
) -> None:
    async with running_daemon(tmp_path) as daemon:
        daemon.agent.set_key("anthropic", KEY)
        folder = await picked(daemon, tmp_path / "project", "a")
        status, room, _ = await daemon.call(
            "POST",
            "/v1/rooms",
            ticket=daemon.ticket(nonce="b"),
            body={
                "folder": folder,
                "agent": {"preset": "anthropic", "model": "claude-opus-5-5"},
            },
        )
        assert status == 201, room
        assert room["agent"] == "Anthropic · claude-opus-5-5"
        (configure,) = daemon.sent_to_host()
        assert configure["type"] == "configure"
        assert configure["config"]["preset"] == "anthropic"
        assert configure["config"]["api_key"] == KEY
        assert KEY not in json.dumps(room)


async def test_a_room_without_a_choice_uses_the_computers_agent(tmp_path: Path) -> None:
    async with running_daemon(tmp_path) as daemon:
        folder = await picked(daemon, tmp_path / "project", "a")
        status, room, _ = await daemon.call(
            "POST", "/v1/rooms", ticket=daemon.ticket(nonce="b"), body={"folder": folder}
        )
        assert status == 201, room
        assert room["agent"].startswith("Demo")


async def test_an_agent_that_is_not_ready_starts_no_host(tmp_path: Path) -> None:
    async with running_daemon(tmp_path) as daemon:
        folder = await picked(daemon, tmp_path / "project", "a")
        status, body, _ = await daemon.call(
            "POST",
            "/v1/rooms",
            ticket=daemon.ticket(nonce="b"),
            body={"folder": folder, "agent": {"preset": "anthropic"}},
        )
        assert (status, body["error"]["code"]) == (409, "agent_not_ready")
        assert "API key" in body["error"]["message"]
        assert daemon.sent_to_host() == []
        _, listing, _ = await daemon.call("GET", "/v1/rooms", ticket=daemon.ticket(nonce="c"))
        assert listing["rooms"] == []


async def test_a_host_that_refuses_the_agent_is_stopped_and_says_why(tmp_path: Path) -> None:
    async with running_daemon(tmp_path) as daemon:
        folder = await picked(daemon, tmp_path / "project", "a")
        status, body, _ = await daemon.call(
            "POST",
            "/v1/rooms",
            ticket=daemon.ticket(nonce="b"),
            body={"folder": folder, "agent": {"preset": "codex_cli", "model": "refuse"}},
        )
        assert (status, body["error"]["code"]) == (409, "agent_failed")
        assert body["error"]["message"] == "not installed"
        _, listing, _ = await daemon.call("GET", "/v1/rooms", ticket=daemon.ticket(nonce="c"))
        assert listing["rooms"] == []


async def test_a_running_rooms_agent_can_be_switched(tmp_path: Path) -> None:
    async with running_daemon(tmp_path) as daemon:
        folder = await picked(daemon, tmp_path / "project", "a")
        _, room, _ = await daemon.call(
            "POST", "/v1/rooms", ticket=daemon.ticket(nonce="b"), body={"folder": folder}
        )
        status, switched, _ = await daemon.call(
            "PUT",
            f"/v1/rooms/{room['room']}/agent",
            ticket=daemon.ticket(nonce="c"),
            body={"agent": {"preset": "ollama", "model": "qwen3:4b"}},
        )
        assert (status, switched["agent"]) == (200, "Ollama (local) · qwen3:4b")
        status, body, _ = await daemon.call(
            "PUT",
            "/v1/rooms/r_none/agent",
            ticket=daemon.ticket(nonce="d"),
            body={"agent": {"preset": "demo"}},
        )
        assert (status, body["error"]["code"]) == (404, "no_room")
        _, listing, _ = await daemon.call("GET", "/v1/rooms", ticket=daemon.ticket(nonce="e"))
        assert listing["rooms"][0]["agent"] == "Ollama (local) · qwen3:4b"


async def test_the_computers_agent_is_saved_and_tested_from_the_page(tmp_path: Path) -> None:
    async with running_daemon(tmp_path) as daemon:
        status, body, _ = await daemon.call(
            "POST",
            "/v1/agent/test",
            ticket=daemon.ticket(nonce="t"),
            body={"choice": {"preset": "demo"}},
        )
        assert status == 200
        assert body["message"].startswith("answered in")
        status, body, _ = await daemon.call(
            "POST",
            "/v1/agent/test",
            ticket=daemon.ticket(nonce="u"),
            body={"choice": {"preset": "anthropic"}},
        )
        assert (status, body["error"]["code"]) == (409, "agent_failed")
        status, body, _ = await daemon.call(
            "PUT",
            "/v1/agent",
            ticket=daemon.ticket(nonce="v"),
            body={"agent": {"preset": "anthropic"}},
        )
        assert (status, body["error"]["code"]) == (409, "agent_not_ready")
        status, _, _ = await daemon.call(
            "PUT",
            "/v1/agent",
            ticket=daemon.ticket(nonce="w"),
            body={"agent": {"preset": "ollama", "model": "qwen3:4b"}},
        )
        assert status == 204
        assert daemon.agent.store.current().preset == "ollama"


async def test_signing_in_opens_a_terminal_with_a_command_the_daemon_chose(tmp_path: Path) -> None:
    async with running_daemon(tmp_path) as daemon:
        status, body, _ = await daemon.call(
            "POST", "/v1/agent/sign-in", ticket=daemon.ticket(nonce="a"), body={"tool": "claude"}
        )
        assert (status, body["command"]) == (200, "claude auth login")
        await daemon.call(
            "POST", "/v1/agent/sign-in", ticket=daemon.ticket(nonce="b"), body={"tool": "codex"}
        )
        assert daemon.terminal.ran == ["claude auth login", "codex login"]
        status, body, _ = await daemon.call(
            "POST", "/v1/agent/sign-in", ticket=daemon.ticket(nonce="c"), body={"tool": "rm -rf"}
        )
        assert (status, body["error"]["code"]) == (400, "bad_request")
        daemon.terminal.unavailable = True
        status, body, _ = await daemon.call(
            "POST", "/v1/agent/sign-in", ticket=daemon.ticket(nonce="d"), body={"tool": "claude"}
        )
        assert (status, body["error"]["code"], body["error"]["command"]) == (
            409,
            "no_terminal",
            "claude auth login",
        )


async def test_installing_needs_a_known_tool_or_extra(tmp_path: Path) -> None:
    async with running_daemon(tmp_path) as daemon:
        for nonce, body in (("a", {}), ("b", {"tool": "bash"}), ("c", {"extra": "evil"})):
            status, answer, _ = await daemon.call(
                "POST", "/v1/agent/install", ticket=daemon.ticket(nonce=nonce), body=body
            )
            assert (status, answer["error"]["code"]) == (400, "bad_request")


# --- the relay a room goes through -----------------------------------------------------------


def relay_of(arguments: list[str]) -> str | None:
    return arguments[arguments.index("--relay") + 1] if "--relay" in arguments else None


async def test_a_room_goes_through_the_relay_the_page_names_and_it_is_remembered(
    tmp_path: Path,
) -> None:
    own = "wss://relay.example.org"
    async with running_daemon(tmp_path) as daemon:
        status, settings, _ = await daemon.call(
            "GET", "/v1/settings", ticket=daemon.ticket(nonce="s")
        )
        assert (status, settings) == (200, {"relay": None})
        folder = await picked(daemon, tmp_path / "one", "a")
        status, _, _ = await daemon.call(
            "POST",
            "/v1/rooms",
            ticket=daemon.ticket(nonce="b"),
            body={"folder": folder, "relay": own},
        )
        assert status == 201
        folder = await picked(daemon, tmp_path / "two", "c")
        await daemon.call(
            "POST", "/v1/rooms", ticket=daemon.ticket(nonce="d"), body={"folder": folder}
        )
        assert [relay_of(arguments) for arguments in daemon.host_arguments()] == [own, own]
        _, settings, _ = await daemon.call("GET", "/v1/settings", ticket=daemon.ticket(nonce="e"))
        assert settings == {"relay": own}
        assert daemon.agent.store.relay() == own
        folder = await picked(daemon, tmp_path / "three", "f")
        await daemon.call(
            "POST",
            "/v1/rooms",
            ticket=daemon.ticket(nonce="g"),
            body={"folder": folder, "relay": ""},
        )
        assert relay_of(daemon.host_arguments()[-1]) is None
        assert daemon.agent.store.relay() == ""


async def test_a_relay_that_is_not_one_is_refused_and_starts_nothing(tmp_path: Path) -> None:
    async with running_daemon(tmp_path) as daemon:
        for nonce, bad in (
            ("a", "https://relay.example.org"),
            ("b", "wss://user:pw@relay.example"),
            ("c", "wss://"),
        ):
            folder = await picked(daemon, tmp_path / f"p{nonce}", f"pick{nonce}")
            status, body, _ = await daemon.call(
                "POST",
                "/v1/rooms",
                ticket=daemon.ticket(nonce=nonce),
                body={"folder": folder, "relay": bad},
            )
            assert (status, body["error"]["code"]) == (400, "bad_relay"), bad
        assert daemon.host_arguments() == []
