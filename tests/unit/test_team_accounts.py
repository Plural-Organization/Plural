"""Teams whose members are accounts (ADR 0016): one person, one member, a key per device."""

import sqlite3
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from plural.protocol.entitlement import EntitlementClaims
from plural.protocol.team import (
    AccountProof,
    MemberClaims,
    MyTeams,
    TeamCreate,
    TeamGrant,
    TeamJoin,
    TeamRole,
    account_proof_message,
    key_proof_message,
)
from plural.protocol.ticket import TicketClaims
from plural.relay.account_proofs import AccountProofs
from plural.relay.directory import DirectoryError, TeamDirectory, TeamLimits, normalize_code
from plural.security.entitlement import EntitlementVerifier
from plural.security.identity import CertVerifier, Identity, authorization
from plural.security.tokens import b64encode

START = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now


class Accounts:
    """Stands in for AccountProofs: a proof's ticket is the account it names."""

    def account_of(self, proof: AccountProof, now: datetime) -> str:
        assert proof.ticket is not None
        return proof.ticket


def as_account(account: str) -> AccountProof:
    return AccountProof(ticket=account)


def person() -> Identity:
    return Identity(Ed25519PrivateKey.generate())


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
async def directory(clock: Clock) -> AsyncGenerator[TeamDirectory]:
    opened = await TeamDirectory.open(Path(":memory:"), clock=clock, accounts=Accounts())
    yield opened
    await opened.close()


async def refused(work: object, status: int) -> str:
    with pytest.raises(DirectoryError) as caught:
        await work  # type: ignore[misc]
    assert caught.value.status == status
    return caught.value.message


async def act(
    directory: TeamDirectory,
    device: Identity,
    grant: TeamGrant,
    clock: Clock,
    method: str,
    tail: str,
    nonce: str,
    certificate: str | None = None,
) -> MemberClaims:
    path = f"/teams/{grant.team_id}/{tail}"
    header = authorization(
        device,
        certificate or grant.certificate,
        method,
        path,
        b"",
        timestamp=int(clock.now.timestamp()),
        nonce=nonce,
    )
    return await directory.authenticate(grant.team_id, header, method, path, b"")


async def test_one_account_is_one_member_on_every_device(
    directory: TeamDirectory, clock: Clock
) -> None:
    owner, laptop, browser = person(), person(), person()
    team = await directory.create(
        TeamCreate(name="Backend", member_name="Vlad", key=owner.public_b64)
    )
    code = team.invite or ""
    first = await directory.join(
        TeamJoin(code=code, name="Alia", key=laptop.public_b64, proof=as_account("a_alia"))
    )
    second = await directory.join(
        TeamJoin(code=code, name="ignored", key=browser.public_b64, proof=as_account("a_alia"))
    )
    assert second.member.id == first.member.id
    assert second.member.name == "Alia"
    for device, grant, nonce in ((laptop, first, "n1"), (browser, second, "n2")):
        claims = await act(directory, device, grant, clock, "GET", "members", nonce)
        assert claims.member == first.member.id
    listing = await directory.members(claims)
    assert [member.name for member in listing.members] == ["Vlad", "Alia"]


async def test_a_signed_in_device_gets_all_its_teams_without_an_invite(
    directory: TeamDirectory, clock: Clock
) -> None:
    laptop, phone = person(), person()
    backend = await directory.create(
        TeamCreate(
            name="Backend", member_name="Vlad", key=laptop.public_b64, proof=as_account("a_v")
        )
    )
    other = await directory.create(
        TeamCreate(name="Infra", member_name="Owner", key=person().public_b64)
    )
    await directory.join(
        TeamJoin(
            code=other.invite or "", name="Vlad", key=laptop.public_b64, proof=as_account("a_v")
        )
    )
    mine = await directory.mine(MyTeams(key=phone.public_b64, proof=as_account("a_v")))
    assert [(grant.team_name, grant.member.role) for grant in mine.teams] == [
        ("Backend", TeamRole.OWNER),
        ("Infra", TeamRole.MEMBER),
    ]
    for grant in mine.teams:
        claims = CertVerifier(grant.team_key).verify(grant.certificate, now=clock.now)
        assert claims.key == phone.public_b64
    claims = await act(directory, phone, mine.teams[0], clock, "GET", "members", "m1")
    assert claims.team == backend.team_id
    nobody = await directory.mine(MyTeams(key=person().public_b64, proof=as_account("a_none")))
    assert nobody.teams == ()


async def test_a_key_only_member_is_claimed_only_with_a_signature_by_its_key(
    directory: TeamDirectory,
) -> None:
    terminal = person()
    team = await directory.create(
        TeamCreate(name="Backend", member_name="Vlad", key=person().public_b64)
    )
    code = team.invite or ""
    old = await directory.join(TeamJoin(code=code, name="Alia", key=terminal.public_b64))
    taking = TeamJoin(code=code, name="Mallory", key=terminal.public_b64, proof=as_account("a_m"))
    assert await refused(directory.join(taking), 409) == "this key is already in the team"
    forged = taking.model_copy(update={"key_proof": person().sign(key_proof_message("x"))})
    assert await refused(directory.join(forged), 401) == "the key did not sign the invite code"
    proof = terminal.sign(key_proof_message(normalize_code(code)))
    claimed = await directory.join(
        TeamJoin(
            code=code,
            name="Alia",
            key=terminal.public_b64,
            proof=as_account("a_alia"),
            key_proof=proof,
        )
    )
    assert claimed.member.id == old.member.id
    mine = await directory.mine(MyTeams(key=person().public_b64, proof=as_account("a_alia")))
    assert [grant.member.id for grant in mine.teams] == [old.member.id]


async def test_a_key_of_someone_else_is_not_taken_by_my_teams(directory: TeamDirectory) -> None:
    shared = person()
    team = await directory.create(
        TeamCreate(name="Backend", member_name="Vlad", key=shared.public_b64)
    )
    await directory.join(
        TeamJoin(
            code=team.invite or "", name="Alia", key=person().public_b64, proof=as_account("a_a")
        )
    )
    message = await refused(
        directory.mine(MyTeams(key=shared.public_b64, proof=as_account("a_a"))), 409
    )
    assert message == "this key belongs to someone else in the team"


async def test_an_account_owns_at_most_three_teams_whatever_key_it_uses(
    directory: TeamDirectory,
) -> None:
    for name in ("One", "Two", "Three"):
        await directory.create(
            TeamCreate(
                name=name, member_name="Vlad", key=person().public_b64, proof=as_account("a_v")
            )
        )
    fourth = TeamCreate(
        name="Four", member_name="Vlad", key=person().public_b64, proof=as_account("a_v")
    )
    assert "you already own 3 teams" in await refused(directory.create(fourth), 429)


async def test_devices_per_member_are_limited(clock: Clock) -> None:
    directory = await TeamDirectory.open(
        Path(":memory:"),
        clock=clock,
        accounts=Accounts(),
        limits=TeamLimits(max_keys_per_member=2),
    )
    try:
        await directory.create(
            TeamCreate(
                name="Backend", member_name="Vlad", key=person().public_b64, proof=as_account("a_v")
            )
        )
        await directory.mine(MyTeams(key=person().public_b64, proof=as_account("a_v")))
        third = directory.mine(MyTeams(key=person().public_b64, proof=as_account("a_v")))
        assert "too many devices" in await refused(third, 409)
    finally:
        await directory.close()


async def test_an_owner_hands_the_team_over_and_the_old_certificate_stops_being_owner(
    directory: TeamDirectory, clock: Clock
) -> None:
    vlad, alia = person(), person()
    team = await directory.create(
        TeamCreate(name="Backend", member_name="Vlad", key=vlad.public_b64)
    )
    joined = await directory.join(
        TeamJoin(code=team.invite or "", name="Alia", key=alia.public_b64)
    )
    owner = await act(directory, vlad, team, clock, "POST", "owner", "o1")
    handed = await directory.hand_over(owner, "alia")
    assert (handed.name, handed.role) == ("Alia", TeamRole.OWNER)
    # Vlad's certificate still says owner until it is renewed; the directory does not trust it.
    stale = await act(directory, vlad, team, clock, "POST", "invites", "o2")
    assert stale.role is TeamRole.OWNER
    assert await refused(directory.invite(stale), 403) == "only the team owner can do that"
    renewed = await directory.renew(stale)
    fresh = CertVerifier(team.team_key).verify(renewed.certificate, now=clock.now)
    assert fresh.role is TeamRole.MEMBER
    alia_claims = await act(directory, alia, joined, clock, "POST", "invites", "o3")
    assert (await directory.invite(alia_claims)).code.startswith("tm-")
    left = await directory.remove(stale, stale.member)
    assert left.name == "Vlad"


async def test_a_relay_without_accounts_refuses_account_proofs(clock: Clock) -> None:
    directory = await TeamDirectory.open(Path(":memory:"), clock=clock)
    try:
        asked = TeamCreate(
            name="Backend", member_name="Vlad", key=person().public_b64, proof=as_account("a_v")
        )
        message = await refused(directory.create(asked), 400)
        assert message == "this relay does not know an accounts service"
        plain = await directory.create(
            TeamCreate(name="Backend", member_name="Vlad", key=person().public_b64)
        )
        assert plain.member.role is TeamRole.OWNER
    finally:
        await directory.close()


async def test_teams_from_before_accounts_keep_working(tmp_path: Path, clock: Clock) -> None:
    path = tmp_path / "teams.db"
    owner = person()
    before = await TeamDirectory.open(path, clock=clock)
    team = await before.create(TeamCreate(name="Backend", member_name="Vlad", key=owner.public_b64))
    await before.close()
    with sqlite3.connect(path) as db:
        # As a relay from before ADR 0016 left it: no account column, no member_keys table.
        db.executescript(
            """
            DROP TABLE member_keys;
            DROP INDEX IF EXISTS members_account;
            CREATE TABLE members_old (
                team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                id TEXT NOT NULL,
                name TEXT NOT NULL,
                key TEXT NOT NULL,
                role TEXT NOT NULL,
                joined_at TEXT NOT NULL,
                PRIMARY KEY (team_id, id)
            );
            INSERT INTO members_old SELECT team_id, id, name, key, role, joined_at FROM members;
            DROP TABLE members;
            ALTER TABLE members_old RENAME TO members;
            CREATE UNIQUE INDEX members_name ON members (team_id, lower(name));
            """
        )
    after = await TeamDirectory.open(path, clock=clock, accounts=Accounts())
    try:
        claims = await act(after, owner, team, clock, "GET", "members", "n1")
        assert claims.role is TeamRole.OWNER
        joined = await after.join(
            TeamJoin(
                code=team.invite or "",
                name="Alia",
                key=person().public_b64,
                proof=as_account("a_a"),
            )
        )
        assert joined.member.name == "Alia"
    finally:
        await after.close()


# --- proving an account ---------------------------------------------------------------------


def signed(key: Ed25519PrivateKey, claims: EntitlementClaims | TicketClaims) -> str:
    body = claims.model_dump_json().encode()
    return f"{b64encode(body)}.{b64encode(key.sign(body))}"


class Suspicion:
    def __init__(self) -> None:
        self.raised = 0

    def __call__(self) -> None:
        self.raised += 1


def ticket(key: Ed25519PrivateKey, audience: str, nonce: str = "nonce-001") -> str:
    claims = TicketClaims.model_validate(
        {
            "aud": audience,
            "account": "a_alia",
            "nonce": nonce,
            "iat": START,
            "exp": START + timedelta(seconds=60),
        }
    )
    return signed(key, claims)


def test_a_browser_proves_its_account_with_a_teams_ticket_once() -> None:
    accounts = Ed25519PrivateKey.generate()
    proofs = AccountProofs(lambda: EntitlementVerifier(accounts.public_key()))
    proof = AccountProof(ticket=ticket(accounts, "teams"))
    assert proofs.account_of(proof, START) == "a_alia"
    with pytest.raises(DirectoryError, match="already used"):
        proofs.account_of(proof, START)
    with pytest.raises(DirectoryError, match="wrong_audience"):
        proofs.account_of(AccountProof(ticket=ticket(accounts, "daemon", "nonce-002")), START)


def test_a_computer_proves_its_account_with_its_certificate() -> None:
    accounts = Ed25519PrivateKey.generate()
    host = person()
    certificate = signed(
        accounts,
        EntitlementClaims(
            account="a_alia", key=host.public_b64, iat=START, exp=START + timedelta(days=7)
        ),
    )
    proofs = AccountProofs(lambda: EntitlementVerifier(accounts.public_key()))
    ts = int(START.timestamp())

    def proof(nonce: str, by: Identity = host, at: int = ts) -> AccountProof:
        return AccountProof(
            certificate=certificate,
            ts=at,
            nonce=nonce,
            signature=by.sign(account_proof_message(at, nonce)),
        )

    assert proofs.account_of(proof("nonce-0001"), START) == "a_alia"
    with pytest.raises(DirectoryError, match="already used"):
        proofs.account_of(proof("nonce-0001"), START)
    with pytest.raises(DirectoryError, match="did not sign"):
        proofs.account_of(proof("nonce-0002", by=person()), START)
    with pytest.raises(DirectoryError, match="clock is off"):
        proofs.account_of(proof("nonce-0003", at=ts - 600), START)


def test_a_forged_proof_makes_the_relay_read_the_accounts_key_again() -> None:
    suspicion = Suspicion()
    proofs = AccountProofs(
        lambda: EntitlementVerifier(Ed25519PrivateKey.generate().public_key()), suspect=suspicion
    )
    with pytest.raises(DirectoryError, match="forged"):
        proofs.account_of(AccountProof(ticket=ticket(Ed25519PrivateKey.generate(), "teams")), START)
    assert suspicion.raised == 1


def test_no_accounts_key_yet_means_try_again() -> None:
    proofs = AccountProofs(lambda: None)
    with pytest.raises(DirectoryError) as caught:
        proofs.account_of(AccountProof(ticket="x"), START)
    assert caught.value.status == 503


def test_a_proof_needs_a_ticket_or_a_signed_certificate() -> None:
    accounts = Ed25519PrivateKey.generate()
    proofs = AccountProofs(lambda: EntitlementVerifier(accounts.public_key()))
    with pytest.raises(DirectoryError) as caught:
        proofs.account_of(AccountProof(certificate="a.b"), START)
    assert caught.value.status == 400


def test_an_invite_code_is_signed_the_way_the_web_client_signs_it() -> None:
    # client/test/team-accounts.test.ts checks the same strings.
    assert normalize_code("TM-ABcde-12345") == "abcde12345"
    assert normalize_code("abcde 12345") == "abcde12345"
    assert key_proof_message(normalize_code("tm-abcde-12345")) == b"plural-team-key:abcde12345"
    assert account_proof_message(1700000000, "n-1") == b"plural-teams:1700000000:n-1"
