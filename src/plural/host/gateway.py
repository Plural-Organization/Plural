from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta

from plural.core.errors import Unauthorized
from plural.core.ports import Clock, IdGenerator
from plural.host.invites import InviteBook, RoomLink
from plural.protocol.capability import CapabilityClaims
from plural.protocol.commands import SessionHello
from plural.protocol.models import (
    HOST_PARTICIPANT_ID,
    AdmissionMode,
    Participant,
    Role,
    SessionState,
)
from plural.security.tokens import InvalidToken, TokenSigner, TokenVerifier


@dataclass(frozen=True, slots=True)
class Admission:
    participant: Participant
    token: str


@dataclass(frozen=True, slots=True)
class NeedsApproval:
    name: str
    client: str


class Gateway:
    def __init__(
        self,
        *,
        room: str,
        signer: TokenSigner,
        invites: InviteBook,
        link: RoomLink,
        ids: IdGenerator,
        clock: Clock,
        token_ttl_s: int,
        previous_hosts: Mapping[str, str] | None = None,
    ) -> None:
        # The keys of hosts that handed this room over, each with the participant it became.
        self._previous = dict(previous_hosts or {})
        self._room = room
        self._signer = signer
        self._invites = invites
        self._link = link
        self._ids = ids
        self._clock = clock
        self._ttl = timedelta(seconds=token_ttl_s)

    def issue(self, participant: Participant) -> str:
        now = self._clock.now()
        claims = CapabilityClaims(
            room=self._room,
            participant=participant.id,
            role=participant.role,
            iat=now,
            exp=now + self._ttl,
            jti=self._ids.new("t_"),
        )
        return self._signer.sign(claims)

    def admit_approved(self, name: str, role: Role) -> Admission:
        participant = Participant(id=self._ids.new("p_"), name=name, role=role)
        return Admission(participant, self.issue(participant))

    def admit(self, hello: SessionHello, state: SessionState) -> Admission | NeedsApproval:
        if hello.token is not None:
            return Admission(self.identify(hello.token, state), hello.token)
        if hello.invite is not None:
            invite = self._invites.redeem(hello.invite)
            participant = Participant(
                id=self._ids.new("p_"), name=hello.name or "guest", role=invite.role
            )
            return Admission(participant, self.issue(participant))
        if hello.join is not None:
            if not self._link.matches(hello.join):
                raise Unauthorized(
                    "this room link is no longer valid, ask the host for the new one"
                )
            name = hello.name or "guest"
            if state.admission is AdmissionMode.OPEN:
                return self.admit_approved(name, Role.PARTICIPANT)
            return NeedsApproval(name=name, client=f"{hello.client.kind} {hello.client.version}")
        raise Unauthorized("an invite, the room link or a token is required")

    def identify(self, token: str, state: SessionState) -> Participant:
        try:
            claims = self._signer.verifier.verify(token, now=self._clock.now())
            person = claims.participant
        except InvalidToken as error:
            claims, person = self._identify_before(token, error)
        if claims.room != self._room:
            raise Unauthorized("token belongs to another room")
        participant = state.participants.get(person)
        if participant is None:
            raise Unauthorized("access revoked")
        return participant

    def _identify_before(self, token: str, refusal: InvalidToken) -> tuple[CapabilityClaims, str]:
        """A token a host before this one signed. The host's own token (`p_host`) was its holder's,
        who is a participant now, so it stands for them and never for the host."""
        for key, former in self._previous.items():
            try:
                claims = TokenVerifier.from_b64(key).verify(token, now=self._clock.now())
            except (InvalidToken, ValueError):
                continue
            return (
                claims,
                former if claims.participant == HOST_PARTICIPANT_ID else claims.participant,
            )
        raise Unauthorized(str(refusal)) from refusal
