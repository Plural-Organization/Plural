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

from plural.daemon.app import create_app
from plural.daemon.folders import FolderPickerUnavailable, Folders
from plural.daemon.rooms import Rooms
from plural.host.account import AccountStore, Entitlement
from plural.protocol.entitlement import EntitlementClaims
from plural.protocol.ticket import TicketClaims
from plural.security.accounts_key import AccountsKey
from plural.security.entitlement import EntitlementVerifier
from plural.security.tokens import b64encode

WEB = "https://web.example.com"

FAKE_HOST = """
import json, sys
if "break_it" in " ".join(sys.argv):
    sys.stderr.write("no provider configured")
    sys.exit(3)
room = "r_" + sys.argv[sys.argv.index("--workspace") + 1][-6:].replace("/", "")
print(json.dumps({
    "type": "ready", "room": room, "guest_link": "wss://relay.example/r_x",
    "host_link": "wss://relay.example/r_x?token=t", "import_url": None,
    "version": "0", "protocol": 1,
}), flush=True)
sys.stdin.read()
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


@dataclass(slots=True)
class Daemon:
    url: str
    port: int
    accounts: Ed25519PrivateKey
    picker: Picker
    now: datetime

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
        clock=lambda: now,
    )
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    async with asyncio.timeout(10):
        while not (server.started and key.ready):
            await asyncio.sleep(0.01)
    try:
        yield Daemon(f"http://127.0.0.1:{port}", port, accounts, picker, now)
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
        assert (status, body["error"]["code"]) == (401, "bad_ticket")
        forged = sign(
            Ed25519PrivateKey.generate(),
            TicketClaims(
                account="a_me", nonce="x", iat=daemon.now, exp=daemon.now + timedelta(seconds=60)
            ),
        )
        status, body, _ = await daemon.call("GET", "/v1/account", ticket=forged)
        assert (status, body["error"]["code"]) == (401, "bad_ticket")
        status, body, _ = await daemon.call("GET", "/v1/account", ticket=daemon.ticket("a_other"))
        assert (status, body["error"]["code"], body["error"]["linked_email"]) == (
            403,
            "wrong_account",
            "alia@example.com",
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
