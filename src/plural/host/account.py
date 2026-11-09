import asyncio
import json
import os
import socket
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request

import structlog
from pydantic import ValidationError

from plural.host.relay_http import ConnectFailed, urlopen
from plural.protocol.models import Model
from plural.protocol.relay import USER_AGENT
from plural.security.keys import load_or_create_host_key
from plural.security.tokens import TokenSigner

log = structlog.get_logger(__name__)

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
RENEW_WITHIN = timedelta(hours=24)
REQUEST_TIMEOUT_S = 8
RENEW_TIMEOUT_S = 6


class AccountError(Exception):
    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class Entitlement(Model):
    accounts: str
    email: str
    certificate: str
    plan: Literal["trial", "paid"]
    expires_at: datetime
    plan_ends_at: datetime


def normalize_code(code: str) -> str:
    return "".join(char for char in code.upper() if char in CODE_ALPHABET)


def accounts_base(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise AccountError(f"{url} is not an address, use https://host")
    return f"{parts.scheme}://{parts.netloc}"


def plan_line(entitlement: Entitlement, now: datetime) -> str:
    if entitlement.plan == "paid":
        return "Plan active"
    days = max(0, -(-int((entitlement.plan_ends_at - now).total_seconds()) // 86400))
    return "Trial, 1 day left" if days == 1 else f"Trial, {days} days left"


def _post(base: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        f"{base}{path}",
        data=json.dumps(body).encode(),
        method="POST",
        headers={"user-agent": USER_AGENT, "content-type": "application/json"},
    )
    host = urlsplit(base).netloc
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
            payload: dict[str, Any] = json.loads(response.read())
    except HTTPError as error:
        code = None
        try:
            problem = json.loads(error.read())["error"]
            message, code = str(problem["message"]), str(problem["code"])
        except (ValueError, KeyError, TypeError):
            message = f"the accounts service answered {error.code}"
        raise AccountError(message, code) from error
    except (URLError, TimeoutError, OSError) as error:
        if isinstance(getattr(error, "reason", error), ConnectFailed | TimeoutError):
            raise AccountError(f"{host} did not answer, try again in a moment") from error
        raise AccountError(f"cannot reach {host}") from error
    return payload


class AccountStore:
    def __init__(self, data_dir: Path) -> None:
        self._dir = data_dir.expanduser()

    @property
    def path(self) -> Path:
        return self._dir / "entitlement.json"

    def signer(self) -> TokenSigner:
        return TokenSigner(load_or_create_host_key(self._dir / "host_key"))

    def load(self) -> Entitlement | None:
        try:
            return Entitlement.model_validate_json(self.path.read_text())
        except FileNotFoundError:
            return None
        except (ValidationError, OSError) as error:
            raise AccountError(f"{self.path} is damaged, link this computer again") from error

    def save(self, entitlement: Entitlement) -> None:
        self._dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.path.with_suffix(".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            handle.write(entitlement.model_dump_json())
        temporary.replace(self.path)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)

    async def certificate(self) -> str | None:
        try:
            current = self.load()
        except AccountError:
            return None
        if current is None:
            return None
        if current.expires_at - datetime.now(UTC) < RENEW_WITHIN:
            try:
                current = await asyncio.wait_for(renew(self, current), RENEW_TIMEOUT_S)
            except (AccountError, TimeoutError) as error:
                log.warning("account.renew_failed", error=str(error))
        return current.certificate


def _entitlement(accounts: str, reply: dict[str, Any]) -> Entitlement:
    try:
        return Entitlement(
            accounts=accounts,
            email=reply["email"],
            certificate=reply["certificate"],
            plan=reply["plan"],
            expires_at=reply["expires_at"],
            plan_ends_at=reply["plan_ends_at"],
        )
    except (KeyError, ValidationError) as error:
        raise AccountError("the accounts service answered with something unexpected") from error


async def claim(store: AccountStore, code: str, accounts_url: str) -> Entitlement:
    base = accounts_base(accounts_url)
    wanted = normalize_code(code)
    if len(wanted) != 8:
        raise AccountError("the code is 8 letters and digits, like K7QF-29XD")
    signer = store.signer()
    body = {
        "code": wanted,
        "key": signer.verifier.public_b64(),
        "signature": signer.prove(f"plural-claim:{wanted}".encode()),
    }
    reply = await asyncio.to_thread(_post, base, "/machines/claim", body)
    entitlement = _entitlement(base, reply)
    store.save(entitlement)
    return entitlement


async def renew(store: AccountStore, current: Entitlement) -> Entitlement:
    signer = store.signer()
    key = signer.verifier.public_b64()
    stamp = int(datetime.now(UTC).timestamp())
    body = {
        "key": key,
        "ts": stamp,
        "signature": signer.prove(f"plural-renew:{key}:{stamp}".encode()),
    }
    reply = await asyncio.to_thread(_post, current.accounts, "/machines/renew", body)
    renewed = _entitlement(current.accounts, reply)
    store.save(renewed)
    return renewed


async def pause(seconds: float) -> None:
    await asyncio.sleep(seconds)


async def device_login(
    store: AccountStore,
    accounts_url: str,
    *,
    show: Callable[[str, str], None],
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> Entitlement:
    """Ask for a code, let the person approve it in a browser, collect the certificate."""
    base = accounts_base(accounts_url)
    wait = sleep or pause
    signer = store.signer()
    key = signer.verifier.public_b64()
    name = socket.gethostname().split(".")[0]
    started = await asyncio.to_thread(_post, base, "/device/code", {"key": key, "name": name})
    try:
        device_code = str(started["device_code"])
        url, user_code = str(started["verification_url"]), str(started["user_code"])
        interval, lasts = float(started["interval"]), float(started["expires_in"])
    except (KeyError, TypeError, ValueError) as error:
        raise AccountError("the accounts service answered with something unexpected") from error
    show(url, user_code)
    waited = 0.0
    while waited < lasts:
        await wait(interval)
        waited += interval
        proof = signer.prove(f"plural-device:{device_code}".encode())
        body = {"device_code": device_code, "key": key, "signature": proof}
        try:
            reply = await asyncio.to_thread(_post, base, "/device/token", body)
        except AccountError as error:
            if error.code == "authorization_pending":
                continue
            if error.code == "slow_down":
                interval += 2
                continue
            raise
        entitlement = _entitlement(base, reply)
        store.save(entitlement)
        return entitlement
    raise AccountError("nobody approved the sign-in in time, run plural login again")
