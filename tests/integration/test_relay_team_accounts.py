"""A relay that knows the accounts service lets accounts create teams and fetch them (ADR 0016)."""

import asyncio
import json
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import uvicorn
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tests.e2e.support import free_port

from plural.host.team import account_teams
from plural.protocol.entitlement import EntitlementClaims
from plural.protocol.ticket import TicketClaims
from plural.relay.app import create_app
from plural.relay.entitlements import EntitlementWatch
from plural.security.entitlement import EntitlementVerifier
from plural.security.identity import Identity
from plural.security.tokens import b64encode


def ticket(accounts: Ed25519PrivateKey, nonce: str, audience: str = "teams") -> str:
    now = datetime.now(UTC)
    claims = TicketClaims.model_validate(
        {
            "aud": audience,
            "account": "a_vlad",
            "nonce": nonce,
            "iat": now,
            "exp": now + timedelta(seconds=60),
        }
    )
    body = claims.model_dump_json().encode()
    return f"{b64encode(body)}.{b64encode(accounts.sign(body))}"


def post(url: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        method="POST",
        headers={"content-type": "application/json", "user-agent": "plural/test"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


async def test_an_account_creates_a_team_and_a_new_device_finds_it(tmp_path: Path) -> None:
    accounts = Ed25519PrivateKey.generate()
    watch = EntitlementWatch(
        "https://accounts.example", fetch=lambda _: EntitlementVerifier(accounts.public_key())
    )
    port = free_port()
    app = create_app(teams=tmp_path / "teams.db", entitlements=watch)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    async with asyncio.timeout(10):
        while not (server.started and watch.ready):
            await asyncio.sleep(0.01)
    base = f"http://127.0.0.1:{port}"
    laptop, browser = Identity(Ed25519PrivateKey.generate()), Identity(Ed25519PrivateKey.generate())
    try:
        status, created = await asyncio.to_thread(
            post,
            f"{base}/teams",
            {
                "name": "Backend",
                "member_name": "Vlad",
                "key": laptop.public_b64,
                "proof": {"ticket": ticket(accounts, "nonce-1")},
            },
        )
        assert status == 201, created
        status, mine = await asyncio.to_thread(
            post,
            f"{base}/teams/mine",
            {"key": browser.public_b64, "proof": {"ticket": ticket(accounts, "nonce-2")}},
        )
        assert status == 200, mine
        assert [(team["team_id"], team["member"]["role"]) for team in mine["teams"]] == [
            (created["team_id"], "owner")
        ]
        status, refused = await asyncio.to_thread(
            post,
            f"{base}/teams/mine",
            {
                "key": browser.public_b64,
                "proof": {"ticket": ticket(accounts, "nonce-3", audience="daemon")},
            },
        )
        assert status == 401
        assert "wrong_audience" in refused["error"]

        # A computer of the same account proves it with its certificate and finds the team too.
        computer, host_key = Identity(Ed25519PrivateKey.generate()), Ed25519PrivateKey.generate()
        host = Identity(host_key)
        now = datetime.now(UTC)
        claims = EntitlementClaims(
            account="a_vlad", key=host.public_b64, iat=now, exp=now + timedelta(days=7)
        )
        body = claims.model_dump_json().encode()
        certificate = f"{b64encode(body)}.{b64encode(accounts.sign(body))}"
        found = await account_teams(f"ws://127.0.0.1:{port}", computer, certificate, host.sign)
        assert [(team.team_id, team.member.role.value) for team in found] == [
            (created["team_id"], "owner")
        ]
    finally:
        server.should_exit = True
        await task
