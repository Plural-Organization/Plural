from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from plural.core.errors import Forbidden, Unauthorized
from plural.host.team_admission import (
    TeamAdmission,
    TeamMember,
    member_id_of,
    participant_id_of,
)
from plural.protocol.team import MemberClaims, MemberList, MemberView, TeamRole
from plural.security.identity import CertSigner, Identity, build_team_proof

START = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
ROOM = "r_live"
URL = "wss://relay.example/r_live"


class Clock:
    def __init__(self) -> None:
        self.current = START

    def now(self) -> datetime:
        return self.current

    def advance(self, **delta: float) -> None:
        self.current += timedelta(**delta)


class Roster:
    def __init__(self) -> None:
        self.people: list[MemberView] = []
        self.calls = 0
        self.down = False

    async def __call__(self) -> MemberList:
        self.calls += 1
        if self.down:
            raise OSError("directory unreachable")
        return MemberList(team_id="t_1", team_name="Backend", members=tuple(self.people))


class Setup:
    def __init__(self) -> None:
        self.clock = Clock()
        self.signer = CertSigner.generate()
        self.roster = Roster()
        self.admission = TeamAdmission(
            team_id="t_1",
            team_key=self.signer.public_b64,
            members=self.roster,
            urls=(URL,),
            clock=self.clock,
        )

    def member(self, name: str, *, listed: bool = True) -> Identity:
        identity = Identity(Ed25519PrivateKey.generate())
        if listed:
            self.roster.people.append(
                MemberView(
                    id=identity.member_id,
                    name=name,
                    key=identity.public_b64,
                    role=TeamRole.MEMBER,
                    joined_at=START,
                )
            )
        return identity

    def certificate(
        self,
        identity: Identity,
        name: str,
        *,
        team: str = "t_1",
        ttl: timedelta = timedelta(days=30),
    ) -> str:
        claims = MemberClaims(
            team=team,
            member=identity.member_id,
            key=identity.public_b64,
            name=name,
            role=TeamRole.MEMBER,
            iat=START,
            exp=START + ttl,
        )
        return self.signer.sign(claims)

    def proof(
        self,
        identity: Identity,
        certificate: str,
        *,
        room: str = ROOM,
        url: str = URL,
        nonce: str = "nonce-0001",
        skew: int = 0,
    ):
        return build_team_proof(
            identity,
            certificate,
            url,
            room,
            timestamp=int(self.clock.now().timestamp()) + skew,
            nonce=nonce,
        )


@pytest.fixture
def setup() -> Setup:
    return Setup()


async def refused(call: Awaitable[object], kind: type[Exception], text: str) -> None:
    with pytest.raises(kind, match=text):
        await call


async def test_a_member_with_a_valid_proof_is_admitted(setup: Setup) -> None:
    alia = setup.member("alia")
    proof = setup.proof(alia, setup.certificate(alia, "alia"))
    assert await setup.admission.admit(proof, ROOM) == TeamMember(alia.member_id, "alia")


async def test_a_certificate_of_another_team_or_a_forged_one_is_refused(setup: Setup) -> None:
    alia = setup.member("alia")
    foreign = CertSigner.generate()
    claims = MemberClaims(
        team="t_1",
        member=alia.member_id,
        key=alia.public_b64,
        name="alia",
        role=TeamRole.MEMBER,
        iat=START,
        exp=START + timedelta(days=1),
    )
    await refused(
        setup.admission.admit(setup.proof(alia, foreign.sign(claims)), ROOM),
        Unauthorized,
        "forged",
    )
    await refused(
        setup.admission.admit(setup.proof(alia, setup.certificate(alia, "alia", team="t_2")), ROOM),
        Unauthorized,
        "another team",
    )


async def test_an_expired_certificate_is_refused(setup: Setup) -> None:
    alia = setup.member("alia")
    certificate = setup.certificate(alia, "alia", ttl=timedelta(hours=1))
    setup.clock.advance(hours=2)
    await refused(
        setup.admission.admit(setup.proof(alia, certificate), ROOM), Unauthorized, "expired"
    )


async def test_a_certificate_is_useless_without_its_key(setup: Setup) -> None:
    alia = setup.member("alia")
    thief = Identity(Ed25519PrivateKey.generate())
    certificate = setup.certificate(alia, "alia")
    await refused(
        setup.admission.admit(setup.proof(thief, certificate), ROOM), Unauthorized, "this key"
    )


async def test_a_proof_for_another_room_is_refused(setup: Setup) -> None:
    alia = setup.member("alia")
    proof = setup.proof(alia, setup.certificate(alia, "alia"), room="r_other")
    await refused(setup.admission.admit(proof, ROOM), Unauthorized, "this key")


async def test_a_proof_made_for_another_address_is_refused(setup: Setup) -> None:
    alia = setup.member("alia")
    certificate = setup.certificate(alia, "alia")
    for other in (
        "wss://evil.example/r_live",
        "wss://relay.example/r_other",
        "ws://relay.example/r_live",
    ):
        await refused(
            setup.admission.admit(setup.proof(alia, certificate, url=other), ROOM),
            Unauthorized,
            "another address",
        )


async def test_the_same_address_written_another_way_is_accepted(setup: Setup) -> None:
    alia = setup.member("alia")
    certificate = setup.certificate(alia, "alia")
    for index, spelled in enumerate(
        (
            "WSS://Relay.Example/r_live",
            "wss://relay.example:443/r_live",
            "wss://relay.example/r_live/",
        )
    ):
        proof = setup.proof(alia, certificate, url=spelled, nonce=f"nonce-000{index}")
        assert (await setup.admission.admit(proof, ROOM)).name == "alia"


async def test_a_stale_or_future_proof_is_refused(setup: Setup) -> None:
    alia = setup.member("alia")
    certificate = setup.certificate(alia, "alia")
    for skew in (-300, 300):
        await refused(
            setup.admission.admit(setup.proof(alia, certificate, skew=skew), ROOM),
            Unauthorized,
            "clock",
        )


async def test_a_proof_cannot_be_used_twice(setup: Setup) -> None:
    alia = setup.member("alia")
    certificate = setup.certificate(alia, "alia")
    await setup.admission.admit(setup.proof(alia, certificate), ROOM)
    await refused(
        setup.admission.admit(setup.proof(alia, certificate), ROOM), Unauthorized, "already used"
    )
    await setup.admission.admit(setup.proof(alia, certificate, nonce="nonce-0002"), ROOM)


async def test_someone_the_team_removed_is_refused_even_with_a_valid_certificate(
    setup: Setup,
) -> None:
    alia = setup.member("alia", listed=False)
    await refused(
        setup.admission.admit(setup.proof(alia, setup.certificate(alia, "alia")), ROOM),
        Unauthorized,
        "no longer in the team",
    )


async def test_someone_the_host_removed_stays_out(setup: Setup) -> None:
    alia = setup.member("alia")
    setup.admission.ban(alia.member_id)
    await refused(
        setup.admission.admit(setup.proof(alia, setup.certificate(alia, "alia")), ROOM),
        Forbidden,
        "removed you",
    )
    assert setup.admission.banned == (alia.member_id,)
    assert not await setup.admission.still_member(alia.member_id)


async def test_the_roster_is_asked_for_now_and_then_not_every_time(setup: Setup) -> None:
    alia = setup.member("alia")
    certificate = setup.certificate(alia, "alia")
    await setup.admission.admit(setup.proof(alia, certificate, nonce="nonce-0001"), ROOM)
    await setup.admission.admit(setup.proof(alia, certificate, nonce="nonce-0002"), ROOM)
    assert setup.roster.calls == 1
    setup.clock.advance(seconds=31)
    await setup.admission.admit(setup.proof(alia, certificate, nonce="nonce-0003"), ROOM)
    assert setup.roster.calls == 2


async def test_a_removal_is_noticed_once_the_roster_is_refreshed(setup: Setup) -> None:
    alia = setup.member("alia")
    assert await setup.admission.still_member(alia.member_id)
    setup.roster.people.clear()
    assert await setup.admission.still_member(alia.member_id)
    setup.clock.advance(seconds=31)
    assert not await setup.admission.still_member(alia.member_id)


async def test_an_unreachable_directory_is_forgiven_for_a_while_and_then_not(
    setup: Setup,
) -> None:
    alia = setup.member("alia")
    certificate = setup.certificate(alia, "alia")
    await setup.admission.admit(setup.proof(alia, certificate, nonce="nonce-0001"), ROOM)
    setup.roster.down = True
    setup.clock.advance(seconds=120)
    await setup.admission.admit(setup.proof(alia, certificate, nonce="nonce-0002"), ROOM)
    setup.clock.advance(seconds=300)
    await refused(
        setup.admission.admit(setup.proof(alia, certificate, nonce="nonce-0003"), ROOM),
        Forbidden,
        "cannot check the team",
    )


async def test_a_directory_that_was_never_reachable_admits_nobody() -> None:
    setup = Setup()
    alia = setup.member("alia")
    setup.roster.down = True
    await refused(
        setup.admission.admit(setup.proof(alia, setup.certificate(alia, "alia")), ROOM),
        Forbidden,
        "cannot check the team",
    )


def test_a_team_member_has_a_stable_participant_id() -> None:
    assert participant_id_of("m_0123abcd") == "p_team_0123abcd"
    assert member_id_of("p_team_0123abcd") == "m_0123abcd"
    assert member_id_of("p_01HABC") is None
