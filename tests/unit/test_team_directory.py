import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from plural.protocol.team import MemberClaims, TeamCreate, TeamGrant, TeamJoin, TeamRole
from plural.relay.directory import DirectoryError, TeamDirectory, TeamLimits, normalize_code
from plural.security.identity import CertVerifier, Identity, authorization

START = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
async def directory(clock: Clock) -> AsyncGenerator[TeamDirectory]:
    opened = await TeamDirectory.open(Path(":memory:"), clock=clock)
    yield opened
    await opened.close()


def person() -> Identity:
    return Identity(Ed25519PrivateKey.generate())


async def founded(directory: TeamDirectory, owner: Identity) -> TeamGrant:
    return await directory.create(
        TeamCreate(name="Backend", member_name="Vlad", key=owner.public_b64)
    )


async def signed(
    directory: TeamDirectory,
    identity: Identity,
    grant: TeamGrant,
    clock: Clock,
    method: str,
    tail: str,
    nonce: str = "n1",
) -> MemberClaims:
    path = f"/teams/{grant.team_id}/{tail}"
    header = authorization(
        identity,
        grant.certificate,
        method,
        path,
        b"",
        timestamp=int(clock.now.timestamp()),
        nonce=nonce,
    )
    return await directory.authenticate(grant.team_id, header, method, path, b"")


async def refused(work: object, status: int) -> str:
    with pytest.raises(DirectoryError) as caught:
        await work  # type: ignore[misc]
    assert caught.value.status == status
    return caught.value.message


async def test_creating_a_team_makes_the_creator_its_owner_and_gives_a_code(
    directory: TeamDirectory, clock: Clock
) -> None:
    owner = person()
    grant = await founded(directory, owner)

    claims = CertVerifier(grant.team_key).verify(grant.certificate, now=clock.now)
    assert (claims.name, claims.role, claims.key) == ("Vlad", TeamRole.OWNER, owner.public_b64)
    assert grant.invite is not None
    assert grant.invite.startswith("tm-")
    assert grant.invite_expires_at == clock.now + timedelta(hours=1)


async def test_a_code_adds_one_member_once(directory: TeamDirectory, clock: Clock) -> None:
    owner, alia, bek = person(), person(), person()
    grant = await founded(directory, owner)
    code = grant.invite or ""

    joined = await directory.join(TeamJoin(code=code, name="Alia", key=alia.public_b64))
    assert joined.team_id == grant.team_id
    assert joined.member.role is TeamRole.MEMBER
    assert joined.team_key == grant.team_key
    CertVerifier(grant.team_key).verify(joined.certificate, now=clock.now)

    await refused(directory.join(TeamJoin(code=code, name="Bek", key=bek.public_b64)), 403)


async def test_a_code_works_however_it_was_typed(directory: TeamDirectory) -> None:
    grant = await founded(directory, person())
    code = grant.invite or ""
    assert normalize_code(code.upper().replace("-", " ")) == normalize_code(code)
    joined = await directory.join(
        TeamJoin(code=code.upper().replace("-", ""), name="Alia", key=person().public_b64)
    )
    assert joined.member.name == "Alia"


async def test_a_wrong_or_expired_code_is_refused(directory: TeamDirectory, clock: Clock) -> None:
    grant = await founded(directory, person())
    await refused(
        directory.join(TeamJoin(code="tm-aaaaa-bbbbb", name="Alia", key=person().public_b64)), 403
    )
    clock.advance(hours=1, seconds=1)
    await refused(
        directory.join(TeamJoin(code=grant.invite or "", name="Alia", key=person().public_b64)), 403
    )


async def test_a_taken_name_does_not_burn_the_code(directory: TeamDirectory) -> None:
    grant = await founded(directory, person())
    await refused(
        directory.join(TeamJoin(code=grant.invite or "", name="vlad", key=person().public_b64)), 409
    )
    joined = await directory.join(
        TeamJoin(code=grant.invite or "", name="Alia", key=person().public_b64)
    )
    assert joined.member.name == "Alia"


async def test_the_same_key_cannot_join_twice(directory: TeamDirectory, clock: Clock) -> None:
    owner = person()
    grant = await founded(directory, owner)
    claims = await signed(directory, owner, grant, clock, "POST", "invites")
    second = await directory.invite(claims)
    await refused(
        directory.join(TeamJoin(code=second.code, name="Other", key=owner.public_b64)), 409
    )


async def test_a_team_has_a_size_limit(clock: Clock) -> None:
    small = await TeamDirectory.open(
        Path(":memory:"), limits=TeamLimits(max_members=2), clock=clock
    )
    grant = await founded(small, person())
    await small.join(TeamJoin(code=grant.invite or "", name="Alia", key=person().public_b64))
    owner = person()
    other = await founded(small, owner)
    claims = await signed(small, owner, other, clock, "POST", "invites")
    await small.invite(claims)
    await small.join(TeamJoin(code=other.invite or "", name="Bek", key=person().public_b64))
    await refused(small.invite(claims), 409)
    await small.close()


async def test_there_is_a_limit_on_teams(clock: Clock) -> None:
    capped = await TeamDirectory.open(Path(":memory:"), limits=TeamLimits(max_teams=1), clock=clock)
    await founded(capped, person())
    await refused(founded(capped, person()), 429)
    await capped.close()


async def test_a_signed_request_is_accepted_once(directory: TeamDirectory, clock: Clock) -> None:
    owner = person()
    grant = await founded(directory, owner)
    claims = await signed(directory, owner, grant, clock, "GET", "members", nonce="a")
    assert claims.name == "Vlad"
    await refused(signed(directory, owner, grant, clock, "GET", "members", nonce="a"), 401)
    await signed(directory, owner, grant, clock, "GET", "members", nonce="b")


async def test_a_request_with_a_stale_clock_is_refused(
    directory: TeamDirectory, clock: Clock
) -> None:
    owner = person()
    grant = await founded(directory, owner)
    path = f"/teams/{grant.team_id}/members"
    header = authorization(
        owner,
        grant.certificate,
        "GET",
        path,
        b"",
        timestamp=int(clock.now.timestamp()) - 300,
        nonce="x",
    )
    message = await refused(directory.authenticate(grant.team_id, header, "GET", path, b""), 401)
    assert "clock" in message


async def test_a_request_for_another_path_or_by_another_key_is_refused(
    directory: TeamDirectory, clock: Clock
) -> None:
    owner, thief = person(), person()
    grant = await founded(directory, owner)
    path = f"/teams/{grant.team_id}/members"
    stamp = int(clock.now.timestamp())
    header = authorization(thief, grant.certificate, "GET", path, b"", timestamp=stamp, nonce="y")
    await refused(directory.authenticate(grant.team_id, header, "GET", path, b""), 401)
    good = authorization(owner, grant.certificate, "GET", path, b"", timestamp=stamp, nonce="z")
    await refused(directory.authenticate(grant.team_id, good, "GET", path + "x", b""), 401)
    await refused(directory.authenticate(grant.team_id, None, "GET", path, b""), 401)


async def test_a_certificate_of_one_team_opens_nothing_in_another(
    directory: TeamDirectory, clock: Clock
) -> None:
    mine, theirs = person(), person()
    first = await founded(directory, mine)
    second = await founded(directory, theirs)
    path = f"/teams/{second.team_id}/members"
    header = authorization(
        mine, first.certificate, "GET", path, b"", timestamp=int(clock.now.timestamp()), nonce="q"
    )
    await refused(directory.authenticate(second.team_id, header, "GET", path, b""), 401)


async def test_members_see_each_other_and_only_the_owner_invites_or_removes(
    directory: TeamDirectory, clock: Clock
) -> None:
    owner, alia = person(), person()
    grant = await founded(directory, owner)
    joined = await directory.join(
        TeamJoin(code=grant.invite or "", name="Alia", key=alia.public_b64)
    )

    as_alia = await signed(directory, alia, joined, clock, "GET", "members")
    listing = await directory.members(as_alia)
    assert [member.name for member in listing.members] == ["Vlad", "Alia"]
    assert listing.team_name == "Backend"

    await refused(_async(directory.invite, as_alia), 403)
    await refused(directory.remove(as_alia, "Vlad"), 403)
    await refused(_async(directory.disband, as_alia), 403)


async def test_a_removed_member_loses_access_at_once(
    directory: TeamDirectory, clock: Clock
) -> None:
    owner, alia = person(), person()
    grant = await founded(directory, owner)
    joined = await directory.join(
        TeamJoin(code=grant.invite or "", name="Alia", key=alia.public_b64)
    )
    as_owner = await signed(directory, owner, grant, clock, "GET", "members", nonce="1")

    removed = await directory.remove(as_owner, "alia")
    assert removed.name == "Alia"
    await refused(signed(directory, alia, joined, clock, "GET", "members", nonce="2"), 401)
    assert [m.name for m in (await directory.members(as_owner)).members] == ["Vlad"]


async def test_a_member_may_leave_but_the_owner_may_not(
    directory: TeamDirectory, clock: Clock
) -> None:
    owner, alia = person(), person()
    grant = await founded(directory, owner)
    joined = await directory.join(
        TeamJoin(code=grant.invite or "", name="Alia", key=alia.public_b64)
    )
    as_alia = await signed(directory, alia, joined, clock, "GET", "members")
    as_owner = await signed(directory, owner, grant, clock, "GET", "members", nonce="2")

    await refused(directory.remove(as_owner, as_owner.member), 409)
    await directory.remove(as_alia, as_alia.member)
    await refused(directory.remove(as_owner, "alia"), 404)


async def test_disbanding_deletes_the_team_and_its_codes(
    directory: TeamDirectory, clock: Clock
) -> None:
    owner = person()
    grant = await founded(directory, owner)
    claims = await signed(directory, owner, grant, clock, "GET", "members")
    await directory.disband(claims)
    assert await directory.team_count() == 0
    await refused(
        directory.join(TeamJoin(code=grant.invite or "", name="Alia", key=person().public_b64)), 403
    )


async def test_renewing_gives_a_later_expiry(directory: TeamDirectory, clock: Clock) -> None:
    owner = person()
    grant = await founded(directory, owner)
    claims = await signed(directory, owner, grant, clock, "POST", "renew")
    clock.advance(days=25)
    renewed = await directory.renew(claims)
    fresh = CertVerifier(grant.team_key).verify(renewed.certificate, now=clock.now)
    old = CertVerifier(grant.team_key).verify(grant.certificate, now=START)
    assert fresh.exp > old.exp
    assert (fresh.member, fresh.key, fresh.role) == (old.member, old.key, old.role)


async def test_a_key_that_is_not_a_key_is_refused(directory: TeamDirectory) -> None:
    await refused(directory.create(TeamCreate(name="x", member_name="Vlad", key="nonsense")), 400)


async def _async(method: object, claims: MemberClaims) -> object:
    return await method(claims)  # type: ignore[operator]


async def test_two_people_racing_for_one_code_get_one_seat(directory: TeamDirectory) -> None:
    grant = await founded(directory, person())
    code = grant.invite or ""
    attempts = [
        directory.join(TeamJoin(code=code, name=f"P{index}", key=person().public_b64))
        for index in range(6)
    ]
    results = await asyncio.gather(*attempts, return_exceptions=True)
    assert sum(isinstance(result, TeamGrant) for result in results) == 1
    assert all(
        isinstance(result, TeamGrant)
        or (isinstance(result, DirectoryError) and result.status == 403)
        for result in results
    )


async def test_a_failed_request_does_not_undo_a_parallel_one(directory: TeamDirectory) -> None:
    first = await founded(directory, person())
    second = await founded(directory, person())
    good = directory.join(TeamJoin(code=second.invite or "", name="Alia", key=person().public_b64))
    clash = directory.join(TeamJoin(code=first.invite or "", name="vlad", key=person().public_b64))
    results = await asyncio.gather(good, clash, return_exceptions=True)
    assert isinstance(results[0], TeamGrant)
    assert isinstance(results[1], DirectoryError)
    again = await directory.join(
        TeamJoin(code=first.invite or "", name="Bek", key=person().public_b64)
    )
    assert again.member.name == "Bek"


async def test_an_expired_certificate_is_told_apart_from_a_forged_one(
    directory: TeamDirectory, clock: Clock
) -> None:
    owner = person()
    grant = await founded(directory, owner)
    clock.advance(days=31)
    message = await refused(signed(directory, owner, grant, clock, "GET", "members"), 401)
    assert "has expired" in message
    other = person()
    forged = grant.model_copy(update={"certificate": grant.certificate[:-4] + "AAAA"})
    message = await refused(
        signed(directory, other, forged, clock, "GET", "members", nonce="n9"), 401
    )
    assert "not a member" in message


async def test_a_failure_in_the_middle_of_creating_a_team_leaves_nothing_behind(
    directory: TeamDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*_: object) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(directory, "_new_invite", broken)
    with pytest.raises(RuntimeError):
        await founded(directory, person())
    monkeypatch.undo()
    assert await directory.team_count() == 0
    await founded(directory, person())
    assert await directory.team_count() == 1
