import asyncio
import json
import os
import secrets
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request

from pydantic import ValidationError

from plural.host.relay_http import ConnectFailed, urlopen
from plural.protocol.models import Model
from plural.protocol.relay import USER_AGENT
from plural.protocol.team import (
    Invite,
    MemberList,
    MemberView,
    Renewed,
    SessionList,
    TeamCreate,
    TeamGrant,
    TeamJoin,
)
from plural.security.identity import CertVerifier, Identity, InvalidCertificate, authorization

RENEW_BEFORE = timedelta(days=7)
REQUEST_TIMEOUT_S = 8


class TeamError(Exception):
    pass


class TeamProfile(Model):
    relay: str
    team_id: str
    team_name: str
    team_key: str
    certificate: str
    member: MemberView


def http_base(relay: str) -> str:
    parts = urlsplit(relay.strip())
    scheme = {"ws": "http", "wss": "https", "http": "http", "https": "https"}.get(parts.scheme)
    if scheme is None or not parts.netloc:
        raise TeamError(f"{relay} is not a relay address, use wss://host or ws://host:port")
    return f"{scheme}://{parts.netloc}"


class TeamStore:
    def __init__(self, data_dir: Path) -> None:
        self._dir = data_dir.expanduser()

    @property
    def identity_path(self) -> Path:
        return self._dir / "identity.pem"

    @property
    def profile_path(self) -> Path:
        return self._dir / "team.json"

    def identity(self) -> Identity:
        return Identity.load_or_create(self.identity_path)

    def load(self) -> TeamProfile | None:
        try:
            return TeamProfile.model_validate_json(self.profile_path.read_text())
        except FileNotFoundError:
            return None
        except (ValidationError, OSError) as error:
            raise TeamError(f"{self.profile_path} is damaged, remove it and join again") from error

    def save(self, profile: TeamProfile) -> None:
        self._dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.profile_path.with_suffix(".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            handle.write(profile.model_dump_json())
        temporary.replace(self.profile_path)

    def clear(self) -> None:
        self.profile_path.unlink(missing_ok=True)


def profile_from(relay: str, grant: TeamGrant) -> TeamProfile:
    return TeamProfile(
        relay=relay,
        team_id=grant.team_id,
        team_name=grant.team_name,
        team_key=grant.team_key,
        certificate=grant.certificate,
        member=grant.member,
    )


# Hosts of tunnels that open for one session. Their address changes at every start and a team made
# on one ends with it. A tunnel of your own, on a domain of yours, is not on this list.
TUNNEL_SUFFIXES = (
    ".trycloudflare.com",
    ".ngrok-free.app",
    ".ngrok-free.dev",
    ".ngrok.app",
    ".ngrok.dev",
    ".ngrok.io",
    ".loca.lt",
)
# What a tunnel provider answers for an address nothing listens on any more.
TUNNEL_GONE = frozenset({404, 502, 503, 504, 530})

RelayState = Literal["alive", "dead", "unknown"]


def is_tunnel_host(host: str) -> bool:
    return host.lower().split(":")[0].endswith(TUNNEL_SUFFIXES)


def closed_tunnel(host: str) -> str:
    return (
        f"the tunnel {host} is closed, and the team on it ended with it. "
        "Ask the team owner to start it again and send a new invite"
    )


def relay_state(relay: str) -> RelayState:
    """Whether the relay answers. Only an answer that is not ours means it is gone: a timeout or a
    refused connection may be this machine being offline, so those stay unknown."""
    try:
        with urlopen(
            Request(f"{http_base(relay)}/healthz", headers={"user-agent": USER_AGENT}),
            timeout=REQUEST_TIMEOUT_S / 3,
        ):
            return "alive"
    except HTTPError:
        return "dead"
    except (URLError, TimeoutError, OSError):
        return "unknown"


def tunnel_closed(profile: TeamProfile) -> bool:
    host = urlsplit(http_base(profile.relay)).netloc
    return is_tunnel_host(host) and relay_state(profile.relay) == "dead"


def _read(request: Request) -> bytes:
    # A connection that never opened sent nothing, so one more try is safe for every method.
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
            return response.read()
    except HTTPError:
        raise
    except URLError as error:
        if not isinstance(error.reason, ConnectFailed):
            raise
    with urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
        return response.read()


def _call(method: str, url: str, body: bytes | None, headers: dict[str, str]) -> Any:
    # Cloudflare in front of a relay refuses urllib's default agent (error 1010).
    request = Request(url, data=body, method=method, headers={"user-agent": USER_AGENT, **headers})
    try:
        payload = _read(request)
    except HTTPError as error:
        try:
            message = json.loads(error.read())["error"]
        except (ValueError, KeyError, TypeError):
            host = urlsplit(url).netloc
            if is_tunnel_host(host) and error.code in TUNNEL_GONE:
                raise TeamError(closed_tunnel(host)) from error
            message = f"the relay answered {error.code}"
        raise TeamError(str(message)) from error
    except (URLError, TimeoutError, OSError) as error:
        host = urlsplit(url).netloc
        if isinstance(getattr(error, "reason", error), ConnectFailed | TimeoutError):
            raise TeamError(f"the relay at {host} did not answer, try again in a moment") from error
        raise TeamError(f"cannot reach the relay at {host}") from error
    return json.loads(payload) if payload else None


async def create_team(relay: str, identity: Identity, *, team: str, member: str) -> TeamProfile:
    body = TeamCreate(name=team, member_name=member, key=identity.public_b64)
    answer = await asyncio.to_thread(
        _call,
        "POST",
        f"{http_base(relay)}/teams",
        body.model_dump_json().encode(),
        {"content-type": "application/json"},
    )
    return profile_from(relay, TeamGrant.model_validate(answer))


async def join_team(relay: str, identity: Identity, *, code: str, member: str) -> TeamProfile:
    body = TeamJoin(code=code, name=member, key=identity.public_b64)
    answer = await asyncio.to_thread(
        _call,
        "POST",
        f"{http_base(relay)}/teams/join",
        body.model_dump_json().encode(),
        {"content-type": "application/json"},
    )
    return profile_from(relay, TeamGrant.model_validate(answer))


class DirectoryClient:
    def __init__(self, store: TeamStore, profile: TeamProfile) -> None:
        self._store = store
        self._identity = store.identity()
        self.profile = profile

    async def members(self) -> MemberList:
        return MemberList.model_validate(await self._signed("GET", "members"))

    async def sessions(self) -> SessionList:
        return SessionList.model_validate(await self._signed("GET", "sessions"))

    async def refresh(self) -> TeamProfile:
        await self._renew_if_due()
        return self.profile

    async def invite(self) -> Invite:
        return Invite.model_validate(await self._signed("POST", "invites"))

    async def remove(self, who: str) -> MemberView:
        return MemberView.model_validate(await self._signed("DELETE", f"members/{quote(who)}"))

    async def disband(self) -> None:
        await self._signed("DELETE", "")

    async def _signed(self, method: str, tail: str) -> Any:
        await self._renew_if_due()
        return await self._send(method, tail)

    async def _send(self, method: str, tail: str) -> Any:
        profile = self.profile
        base = http_base(profile.relay)
        path = f"/teams/{profile.team_id}" + (f"/{tail}" if tail else "")
        header = authorization(
            self._identity,
            profile.certificate,
            method,
            path,
            b"",
            timestamp=int(time.time()),
            nonce=secrets.token_hex(8),
        )
        return await asyncio.to_thread(
            _call, method, f"{base}{path}", None, {"authorization": header}
        )

    async def _renew_if_due(self) -> None:
        verifier = CertVerifier(self.profile.team_key)
        now = datetime.now(UTC)
        try:
            claims = verifier.verify(self.profile.certificate, now=now)
        except InvalidCertificate as error:
            raise TeamError(
                f"your certificate is not valid ({error}), join the team again"
            ) from error
        if claims.exp - now > RENEW_BEFORE:
            return
        renewed = Renewed.model_validate(await self._send("POST", "renew"))
        self.profile = self.profile.model_copy(update={"certificate": renewed.certificate})
        self._store.save(self.profile)
