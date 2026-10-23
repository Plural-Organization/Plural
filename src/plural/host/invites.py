import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from plural.core.errors import Unauthorized
from plural.core.ports import Clock
from plural.protocol.models import Role


@dataclass(frozen=True, slots=True)
class Invite:
    code: str
    role: Role
    expires_at: datetime
    link: str


class InviteBook:
    def __init__(self, *, clock: Clock, link_base: str) -> None:
        self._clock = clock
        self._link_base = link_base
        self._invites: dict[str, Invite] = {}

    def create(self, role: Role, ttl_s: int) -> Invite:
        code = secrets.token_urlsafe(12)
        invite = Invite(
            code=code,
            role=role,
            expires_at=self._clock.now() + timedelta(seconds=ttl_s),
            link=f"{self._link_base}?invite={code}",
        )
        self._invites[code] = invite
        return invite

    def redeem(self, code: str) -> Invite:
        invite = self._invites.pop(code, None)
        if invite is None or invite.expires_at <= self._clock.now():
            raise Unauthorized("invite is invalid or expired")
        return invite
