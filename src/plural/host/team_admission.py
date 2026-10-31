from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from plural.core.errors import Forbidden, Unauthorized
from plural.core.ports import Clock
from plural.protocol.commands import TeamProof
from plural.protocol.team import MemberList
from plural.security.identity import (
    CertVerifier,
    InvalidCertificate,
    normalize_url,
    verify_team_proof,
)
from plural.security.replay import ReplayGuard

PARTICIPANT_PREFIX = "p_team_"


@dataclass(frozen=True, slots=True)
class TeamMember:
    id: str
    name: str


def participant_id_of(member_id: str) -> str:
    return PARTICIPANT_PREFIX + member_id.removeprefix("m_")


def member_id_of(participant_id: str) -> str | None:
    if not participant_id.startswith(PARTICIPANT_PREFIX):
        return None
    return "m_" + participant_id.removeprefix(PARTICIPANT_PREFIX)


class TeamAdmission:
    def __init__(
        self,
        *,
        team_id: str,
        team_key: str,
        members: Callable[[], Awaitable[MemberList]],
        clock: Clock,
        urls: Iterable[str] = (),
        banned: Iterable[str] = (),
        roster_ttl_s: float = 30.0,
        roster_stale_s: float = 300.0,
        skew_s: int = 60,
    ) -> None:
        self._team_id = team_id
        self._urls = frozenset(normalize_url(url) for url in urls)
        self._verifier = CertVerifier(team_key)
        self._members = members
        self._clock = clock
        self._banned = set(banned)
        self._ttl = timedelta(seconds=roster_ttl_s)
        self._stale = timedelta(seconds=roster_stale_s)
        self._skew_s = skew_s
        self._roster: dict[str, str] = {}
        self._fetched_at: datetime | None = None
        self._replays = ReplayGuard(timedelta(seconds=2 * skew_s))

    @property
    def banned(self) -> tuple[str, ...]:
        return tuple(sorted(self._banned))

    def ban(self, member_id: str) -> None:
        self._banned.add(member_id)

    async def admit(self, proof: TeamProof, room: str) -> TeamMember:
        now = self._clock.now()
        try:
            claims = self._verifier.verify(proof.certificate, now=now)
        except InvalidCertificate as error:
            raise Unauthorized(f"your team certificate is not valid: {error}") from error
        if claims.team != self._team_id:
            raise Unauthorized("that certificate is for another team")
        if not verify_team_proof(proof, claims, room):
            raise Unauthorized("could not prove that this key is yours")
        if normalize_url(proof.url) not in self._urls:
            raise Unauthorized("that proof was made for another address")
        if abs(int(now.timestamp()) - proof.ts) > self._skew_s:
            raise Unauthorized("your clock is off by more than a minute")
        if not self._replays.fresh(f"{claims.member}:{proof.nonce}", now):
            raise Unauthorized("this join was already used")
        if claims.member in self._banned:
            raise Forbidden("the host removed you from this session")
        if await self._roster_key(claims.member) != claims.key:
            raise Unauthorized("you are no longer in the team")
        return TeamMember(id=claims.member, name=claims.name)

    async def still_member(self, member_id: str) -> bool:
        if member_id in self._banned:
            return False
        return await self._roster_key(member_id) is not None

    async def _roster_key(self, member_id: str) -> str | None:
        now = self._clock.now()
        if self._fetched_at is None or now - self._fetched_at > self._ttl:
            try:
                listing = await self._members()
            except Exception as error:
                if self._fetched_at is None or now - self._fetched_at > self._stale:
                    raise Forbidden("cannot check the team right now, try again") from error
            else:
                self._roster = {person.id: person.key for person in listing.members}
                self._fetched_at = now
        return self._roster.get(member_id)
