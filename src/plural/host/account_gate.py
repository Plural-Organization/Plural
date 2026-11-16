"""Asks the relay, before a room is opened, whether it needs the host to be signed in.

A relay run with `--require-account` closes a host without a valid certificate (ADR 0017). The host
would then retry in the background and say nothing, so it asks `/healthz` first and, when the relay
says it needs an account and this computer has none, stops with what to do.
"""

import asyncio
import json
from datetime import UTC, datetime
from http.client import HTTPException
from typing import cast
from urllib.error import URLError
from urllib.request import Request

from plural.host.account import AccountError, AccountStore
from plural.host.config import HostSettings
from plural.host.relay_http import urlopen
from plural.host.team import TeamError, http_base
from plural.protocol.relay import USER_AGENT

ASK_TIMEOUT_S = 3.0
SIGN_IN = "this relay needs you signed in: run plural login, then start the room again"
EXPIRED = "your sign-in has expired and could not be renewed: run plural login"


class AccountRequired(Exception):
    """The relay will refuse this host, and what the person can do about it."""


def _needs_account(relay: str) -> bool:
    """Whether the relay says it requires an account. Anything unclear counts as no: a relay that
    cannot be reached, or one that predates the field, is judged when the host opens its room."""
    try:
        with urlopen(
            Request(f"{http_base(relay)}/healthz", headers={"user-agent": USER_AGENT}),
            timeout=ASK_TIMEOUT_S,
        ) as response:
            body: object = json.loads(response.read(4096))
    except (OSError, URLError, HTTPException, TeamError, ValueError):
        return False
    if not isinstance(body, dict):
        return False
    answer = cast("dict[str, object]", body)
    return answer.get("accounts") == "required"


async def _asked_and_needs_account(relay: str) -> bool:
    """The answer, within a few seconds however long the connection would take to give up: a host
    that starts while the machine is offline must not wait on a relay it cannot reach."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(_needs_account, relay), ASK_TIMEOUT_S + 1)
    except TimeoutError:
        return False


async def ensure_signed_in(settings: HostSettings) -> None:
    relay = settings.relay_url
    if not relay or not await _asked_and_needs_account(relay):
        return
    store = AccountStore(settings.state_dir)
    # `certificate` renews one that is about to run out, so what is left is what the relay will see.
    if await store.certificate() is None:
        raise AccountRequired(SIGN_IN)
    try:
        held = store.load()
    except AccountError as error:
        raise AccountRequired(SIGN_IN) from error
    if held is None or held.expires_at <= datetime.now(UTC):
        raise AccountRequired(EXPIRED)
