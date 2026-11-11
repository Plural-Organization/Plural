from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from plural.protocol.models import Model

NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$"

MemberName = Annotated[str, Field(pattern=NAME_PATTERN)]
TeamName = Annotated[str, Field(min_length=1, max_length=60)]


class TeamRole(StrEnum):
    OWNER = "owner"
    MEMBER = "member"


class MemberClaims(Model):
    team: str
    member: str
    key: str
    name: MemberName
    role: TeamRole
    iat: datetime
    exp: datetime


class MemberView(Model):
    id: str
    name: MemberName
    key: str
    role: TeamRole
    joined_at: datetime


class AccountProof(Model):
    """That the device asking belongs to an account (ADR 0016).

    A browser sends a `ticket` from the accounts service with `aud: "teams"`. A computer sends its
    entitlement `certificate` and a `signature` by the certificate's key over
    `account_proof_message(ts, nonce)`.
    """

    ticket: str | None = Field(default=None, max_length=4096)
    certificate: str | None = Field(default=None, max_length=4096)
    ts: int | None = None
    nonce: str | None = Field(default=None, min_length=8, max_length=64)
    signature: str | None = Field(default=None, max_length=200)


def account_proof_message(ts: int, nonce: str) -> bytes:
    return f"plural-teams:{ts}:{nonce}".encode()


def key_proof_message(code: str) -> bytes:
    """What a key signs to show it is the joiner's own, so a key-only member can be claimed."""
    return f"plural-team-key:{code}".encode()


class TeamCreate(Model):
    name: TeamName
    member_name: MemberName
    key: str
    proof: AccountProof | None = None


class TeamJoin(Model):
    code: str = Field(min_length=4, max_length=64)
    name: MemberName
    key: str
    proof: AccountProof | None = None
    # A signature by `key` over key_proof_message(code): lets an account take over the key-only
    # member that already has this key, instead of joining a second time.
    key_proof: str | None = Field(default=None, max_length=200)


class MyTeams(Model):
    """A signed-in device asking for every team of its account, with certificates for `key`."""

    key: str
    proof: AccountProof


class OwnerHandover(Model):
    member: str = Field(min_length=1, max_length=64)


class TeamGrant(Model):
    team_id: str
    team_name: str
    team_key: str
    certificate: str
    member: MemberView
    invite: str | None = None
    invite_expires_at: datetime | None = None


class TeamGrants(Model):
    teams: tuple[TeamGrant, ...]


class Invite(Model):
    code: str
    expires_at: datetime | None = None


class MemberList(Model):
    team_id: str
    team_name: str
    members: tuple[MemberView, ...]


class Renewed(Model):
    certificate: str


class SessionStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"


class EndpointKind(StrEnum):
    RELAY = "relay"
    DIRECT = "direct"


class Endpoint(Model):
    kind: EndpointKind
    url: str = Field(min_length=8, max_length=300, pattern=r"^(wss?|https?)://\S+$")


class Touch(Model):
    path: str = Field(min_length=1, max_length=300)
    at: datetime


class Conflict(Model):
    owner: MemberName
    room: str
    branch: str | None = None
    paths: tuple[str, ...] = Field(max_length=10)
    same_branch: bool
    latest: datetime


class Peer(Model):
    owner: MemberName
    room: str
    branch: str | None = None
    same_branch: bool
    touched: tuple[Touch, ...] = Field(max_length=50)


class CardDraft(Model):
    room: str = Field(min_length=1, max_length=64)
    repo: str = Field(min_length=1, max_length=80)
    branch: str | None = Field(default=None, max_length=120)
    title: str | None = Field(default=None, max_length=80)
    status: SessionStatus
    viewers: int = Field(default=0, ge=0, le=1000)
    endpoints: tuple[Endpoint, ...] = Field(min_length=1, max_length=4)
    repo_id: str | None = Field(default=None, max_length=200)
    touching: tuple[Touch, ...] = Field(default=(), max_length=50)
    # The agent the session runs, as the host names it ("Claude Code · claude-sonnet-5-5").
    agent: str | None = Field(default=None, max_length=120)


class SessionCard(CardDraft):
    owner: MemberName
    owner_id: str
    updated_at: datetime
    conflicts: tuple[Conflict, ...] = ()


class SessionList(Model):
    sessions: tuple[SessionCard, ...]


class PresenceCard(Model):
    type: Literal["card"] = "card"
    card: CardDraft


class PresencePeers(Model):
    type: Literal["peers"] = "peers"
    peers: tuple[Peer, ...]
