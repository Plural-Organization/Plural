import asyncio
import hashlib
import os
import secrets
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol, Self

import aiosqlite

from plural.protocol.team import (
    AccountProof,
    Invite,
    MemberClaims,
    MemberList,
    MemberView,
    MyTeams,
    Renewed,
    TeamCreate,
    TeamGrant,
    TeamGrants,
    TeamJoin,
    TeamRole,
    key_proof_message,
)
from plural.security.identity import (
    CertSigner,
    CertVerifier,
    ExpiredCertificate,
    InvalidCertificate,
    InvalidRequest,
    member_id,
    parse_authorization,
    valid_public_key,
    verify_request,
    verify_signature,
)
from plural.security.replay import ReplayGuard

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    signing_key BLOB NOT NULL,
    public_key TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS members (
    team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    key TEXT NOT NULL,
    role TEXT NOT NULL,
    joined_at TEXT NOT NULL,
    account TEXT,
    PRIMARY KEY (team_id, id)
);
CREATE UNIQUE INDEX IF NOT EXISTS members_name ON members (team_id, lower(name));
CREATE TABLE IF NOT EXISTS member_keys (
    team_id TEXT NOT NULL,
    member_id TEXT NOT NULL,
    key TEXT NOT NULL,
    added_at TEXT NOT NULL,
    PRIMARY KEY (team_id, key),
    FOREIGN KEY (team_id, member_id) REFERENCES members (team_id, id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS invites (
    hash TEXT PRIMARY KEY,
    team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    created_by TEXT NOT NULL
);
"""

CODE_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
CODE_LENGTH = 10
CODE_PREFIX = "tm"


class DirectoryError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True, slots=True)
class TeamLimits:
    max_teams: int = 500
    max_teams_per_owner: int = 3
    max_members: int = 50
    certificate_ttl_s: int = 30 * 86_400
    clock_skew_s: int = 60
    # Devices of one account in one team: a browser or computer each.
    max_keys_per_member: int = 20


class AccountCheck(Protocol):
    """Says which account a proof stands for, or raises DirectoryError (relay/account_proofs.py)."""

    def account_of(self, proof: AccountProof, now: datetime) -> str: ...


def normalize_code(code: str) -> str:
    return "".join(character for character in code.lower() if character.isalnum()).removeprefix(
        CODE_PREFIX
    )


def new_code() -> str:
    body = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    return f"{CODE_PREFIX}-{body[:5]}-{body[5:]}"


def code_hash(code: str) -> str:
    return hashlib.sha256(normalize_code(code).encode()).hexdigest()


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _view(row: aiosqlite.Row) -> MemberView:
    return MemberView(
        id=row["id"],
        name=row["name"],
        key=row["key"],
        role=TeamRole(row["role"]),
        joined_at=datetime.fromisoformat(row["joined_at"]),
    )


class TeamDirectory:
    def __init__(
        self,
        db: aiosqlite.Connection,
        *,
        limits: TeamLimits | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        accounts: AccountCheck | None = None,
    ) -> None:
        self._db = db
        self._accounts = accounts
        self._limits = limits or TeamLimits()
        self._clock = clock
        self._replays = ReplayGuard(timedelta(seconds=2 * self._limits.clock_skew_s))
        self._writing = asyncio.Lock()

    @asynccontextmanager
    async def _transaction(self) -> AsyncGenerator[None]:
        async with self._writing:
            try:
                yield
            except BaseException:
                await self._db.rollback()
                raise
            await self._db.commit()

    @classmethod
    async def open(
        cls,
        path: Path,
        *,
        limits: TeamLimits | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        accounts: AccountCheck | None = None,
    ) -> Self:
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.close(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600))
        db = await aiosqlite.connect(path)
        try:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys = ON")
            await db.executescript(SCHEMA)
            await cls._migrate_invites(db)
            await cls._migrate_members(db)
            await db.commit()
        except BaseException:
            # A connection left open keeps its thread, and the relay could never exit.
            await db.close()
            raise
        return cls(db, limits=limits, clock=clock, accounts=accounts)

    @staticmethod
    async def _migrate_members(db: aiosqlite.Connection) -> None:
        """Members from before accounts: an `account` column, and their one key in member_keys."""
        async with db.execute("PRAGMA table_info(members)") as cursor:
            columns = {row["name"] for row in await cursor.fetchall()}
        if "account" not in columns:
            await db.execute("ALTER TABLE members ADD COLUMN account TEXT")
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS members_account ON members (team_id, account)"
            " WHERE account IS NOT NULL"
        )
        await db.execute(
            "INSERT OR IGNORE INTO member_keys (team_id, member_id, key, added_at)"
            " SELECT team_id, id, key, joined_at FROM members"
        )

    @staticmethod
    async def _migrate_invites(db: aiosqlite.Connection) -> None:
        async with db.execute("PRAGMA table_info(invites)") as cursor:
            columns = {row["name"] for row in await cursor.fetchall()}
        if "expires_at" not in columns and "used_by" not in columns:
            return
        await db.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE invites_new (
                hash TEXT PRIMARY KEY,
                team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                created_by TEXT NOT NULL
            );
            INSERT INTO invites_new (hash, team_id, created_by)
                SELECT hash, team_id, created_by FROM invites;
            DROP TABLE invites;
            ALTER TABLE invites_new RENAME TO invites;
            COMMIT;
            """
        )

    async def close(self) -> None:
        await self._db.close()

    async def team_count(self) -> int:
        async with self._db.execute("SELECT count(*) FROM teams") as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def _owned_count(self, key: str) -> int:
        async with self._db.execute(
            "SELECT count(*) FROM members WHERE key = ? AND role = ?", (key, TeamRole.OWNER.value)
        ) as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    def _account(self, proof: AccountProof | None) -> str | None:
        if proof is None:
            return None
        if self._accounts is None:
            raise DirectoryError(400, "this relay does not know an accounts service")
        return self._accounts.account_of(proof, self._clock())

    async def create(self, request: TeamCreate) -> TeamGrant:
        account = self._account(request.proof)
        async with self._transaction():
            if not valid_public_key(request.key):
                raise DirectoryError(400, "that is not a public key")
            if await self.team_count() >= self._limits.max_teams:
                raise DirectoryError(429, "this relay cannot take more teams")
            owned = (
                await self._owned_by_account(account)
                if account is not None
                else await self._owned_count(request.key)
            )
            if owned >= self._limits.max_teams_per_owner:
                raise DirectoryError(
                    429,
                    f"you already own {self._limits.max_teams_per_owner} teams on this relay, "
                    "delete one with plural team disband",
                )
            now = self._clock()
            signer = CertSigner.generate()
            team_id = f"t_{secrets.token_hex(8)}"
            await self._db.execute(
                "INSERT INTO teams (id, name, signing_key, public_key, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (team_id, request.name, signer.to_pem(), signer.public_b64, _iso(now)),
            )
            member = await self._add_member(
                team_id, request.member_name, request.key, TeamRole.OWNER, now, account
            )
            code = await self._new_invite(team_id, member.id)
        return self._grant(team_id, request.name, signer, member, request.key, now, code)

    async def join(self, request: TeamJoin) -> TeamGrant:
        account = self._account(request.proof)
        async with self._transaction():
            if not valid_public_key(request.key):
                raise DirectoryError(400, "that is not a public key")
            now = self._clock()
            async with self._db.execute(
                "SELECT i.team_id, t.name, t.signing_key"
                " FROM invites i JOIN teams t ON t.id = i.team_id WHERE i.hash = ?",
                (code_hash(request.code),),
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                raise DirectoryError(403, "that invite code is wrong")
            team_id: str = row["team_id"]
            member = None if account is None else await self._joined_account(team_id, account)
            if member is not None:
                # The account is in already: this device is one more key of the same member.
                await self._add_key(team_id, member.id, request.key, now)
            elif account is not None and (claimed := await self._claim(team_id, request, account)):
                member = claimed
            else:
                if await self._member_count(team_id) >= self._limits.max_members:
                    raise DirectoryError(409, "this team is full")
                member = await self._add_member(
                    team_id, request.name, request.key, TeamRole.MEMBER, now, account
                )
        signer = CertSigner.from_pem(row["signing_key"])
        return self._grant(team_id, row["name"], signer, member, request.key, now)

    async def mine(self, request: MyTeams) -> TeamGrants:
        """Every team of the account, with a certificate for this device's key."""
        account = self._account(request.proof)
        assert account is not None
        if not valid_public_key(request.key):
            raise DirectoryError(400, "that is not a public key")
        grants: list[TeamGrant] = []
        async with self._transaction():
            now = self._clock()
            async with self._db.execute(
                "SELECT m.team_id, m.id, m.name, m.key, m.role, m.joined_at, t.name AS team_name,"
                " t.signing_key FROM members m JOIN teams t ON t.id = m.team_id"
                " WHERE m.account = ? ORDER BY t.name, t.id",
                (account,),
            ) as cursor:
                rows = await cursor.fetchall()
            for row in rows:
                await self._add_key(row["team_id"], row["id"], request.key, now)
                signer = CertSigner.from_pem(row["signing_key"])
                grants.append(
                    self._grant(
                        row["team_id"], row["team_name"], signer, _view(row), request.key, now
                    )
                )
        return TeamGrants(teams=tuple(grants))

    async def _joined_account(self, team_id: str, account: str) -> MemberView | None:
        async with self._db.execute(
            "SELECT id, name, key, role, joined_at FROM members WHERE team_id = ? AND account = ?",
            (team_id, account),
        ) as cursor:
            row = await cursor.fetchone()
        return None if row is None else _view(row)

    async def _claim(self, team_id: str, request: TeamJoin, account: str) -> MemberView | None:
        """The key-only member that already has this key, now tied to the account.

        Only with a signature by that key: a public key alone proves nothing, and anyone could
        otherwise take over someone's membership by naming their key.
        """
        async with self._db.execute(
            "SELECT m.id, m.name, m.key, m.role, m.joined_at, m.account FROM member_keys k"
            " JOIN members m ON m.team_id = k.team_id AND m.id = k.member_id"
            " WHERE k.team_id = ? AND k.key = ?",
            (team_id, request.key),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        if row["account"] is not None or request.key_proof is None:
            raise DirectoryError(409, "this key is already in the team")
        message = key_proof_message(normalize_code(request.code))
        if not verify_signature(request.key, message, request.key_proof):
            raise DirectoryError(401, "the key did not sign the invite code")
        await self._db.execute(
            "UPDATE members SET account = ? WHERE team_id = ? AND id = ?",
            (account, team_id, row["id"]),
        )
        return _view(row)

    async def _add_key(self, team_id: str, member: str, key: str, now: datetime) -> None:
        async with self._db.execute(
            "SELECT member_id FROM member_keys WHERE team_id = ? AND key = ?", (team_id, key)
        ) as cursor:
            row = await cursor.fetchone()
        if row is not None:
            if row["member_id"] != member:
                raise DirectoryError(409, "this key belongs to someone else in the team")
            return
        async with self._db.execute(
            "SELECT count(*) FROM member_keys WHERE team_id = ? AND member_id = ?",
            (team_id, member),
        ) as cursor:
            counted = await cursor.fetchone()
        if counted is not None and int(counted[0]) >= self._limits.max_keys_per_member:
            raise DirectoryError(409, "too many devices in this team, remove one first")
        await self._db.execute(
            "INSERT INTO member_keys (team_id, member_id, key, added_at) VALUES (?, ?, ?, ?)",
            (team_id, member, key, _iso(now)),
        )

    async def authenticate(
        self, team_id: str, header: str | None, method: str, path: str, body: bytes
    ) -> MemberClaims:
        denied = DirectoryError(401, "you are not a member of this team")
        try:
            signed = parse_authorization(header)
        except InvalidRequest as error:
            raise DirectoryError(401, str(error)) from error
        async with self._db.execute(
            "SELECT public_key FROM teams WHERE id = ?", (team_id,)
        ) as cursor:
            team = await cursor.fetchone()
        if team is None:
            raise denied
        now = self._clock()
        try:
            claims = CertVerifier(team["public_key"]).verify(signed.certificate, now=now)
        except ExpiredCertificate as error:
            raise DirectoryError(
                401, "your team certificate has expired, ask the owner for a new invite"
            ) from error
        except InvalidCertificate as error:
            raise denied from error
        if claims.team != team_id or not await self._is_member(team_id, claims):
            raise denied
        if abs(int(now.timestamp()) - signed.timestamp) > self._limits.clock_skew_s:
            raise DirectoryError(401, "your clock is off by more than a minute")
        if not verify_request(signed, claims, method, path, body):
            raise denied
        if not self._replays.fresh(f"{claims.member}:{signed.nonce}", now):
            raise DirectoryError(401, "this request was already used")
        return claims

    async def still_valid(self, claims: MemberClaims) -> bool:
        return claims.exp > self._clock() and await self._is_member(claims.team, claims)

    async def members(self, claims: MemberClaims) -> MemberList:
        async with self._db.execute(
            "SELECT name FROM teams WHERE id = ?", (claims.team,)
        ) as cursor:
            team = await cursor.fetchone()
        if team is None:
            raise DirectoryError(404, "this team is gone")
        async with self._db.execute(
            "SELECT id, name, key, role, joined_at FROM members WHERE team_id = ?"
            " ORDER BY (role = 'owner') DESC, joined_at, name",
            (claims.team,),
        ) as cursor:
            rows = await cursor.fetchall()
        return MemberList(
            team_id=claims.team,
            team_name=team["name"],
            members=tuple(_view(row) for row in rows),
        )

    async def invite(self, claims: MemberClaims) -> Invite:
        async with self._transaction():
            await self._owner_only(claims)
            if await self._member_count(claims.team) >= self._limits.max_members:
                raise DirectoryError(409, "this team is full")
            code = await self._new_invite(claims.team, claims.member)
        return Invite(code=code)

    async def remove(self, claims: MemberClaims, target: str) -> MemberView:
        async with self._transaction():
            async with self._db.execute(
                "SELECT id, name, key, role, joined_at FROM members WHERE team_id = ?"
                " AND (id = ? OR lower(name) = lower(?))",
                (claims.team, target, target),
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                raise DirectoryError(404, f"nobody called {target} in this team")
            view = _view(row)
            if view.id != claims.member:
                await self._owner_only(claims)
            if view.role is TeamRole.OWNER:
                raise DirectoryError(409, "the owner cannot leave; disband the team instead")
            await self._db.execute(
                "DELETE FROM members WHERE team_id = ? AND id = ?", (claims.team, view.id)
            )
        return view

    async def disband(self, claims: MemberClaims) -> None:
        async with self._transaction():
            await self._owner_only(claims)
            await self._db.execute("DELETE FROM teams WHERE id = ?", (claims.team,))

    async def renew(self, claims: MemberClaims) -> Renewed:
        async with self._db.execute(
            "SELECT t.signing_key, m.name, m.role FROM teams t"
            " JOIN members m ON m.team_id = t.id AND m.id = ? WHERE t.id = ?",
            (claims.member, claims.team),
        ) as cursor:
            team = await cursor.fetchone()
        if team is None:
            raise DirectoryError(404, "this team is gone")
        now = self._clock()
        # Name and role come from the directory, not the old certificate: an owner may have
        # handed the team over since.
        fresh = claims.model_copy(
            update={
                "name": team["name"],
                "role": TeamRole(team["role"]),
                "iat": now,
                "exp": now + timedelta(seconds=self._limits.certificate_ttl_s),
            }
        )
        return Renewed(certificate=CertSigner.from_pem(team["signing_key"]).sign(fresh))

    async def hand_over(self, claims: MemberClaims, target: str) -> MemberView:
        """Make another member the owner; the old owner stays a member and may then leave."""
        async with self._transaction():
            await self._owner_only(claims)
            async with self._db.execute(
                "SELECT id, name, key, role, joined_at FROM members WHERE team_id = ?"
                " AND (id = ? OR lower(name) = lower(?))",
                (claims.team, target, target),
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                raise DirectoryError(404, f"nobody called {target} in this team")
            if row["id"] == claims.member:
                raise DirectoryError(409, "you own this team already")
            await self._db.execute(
                "UPDATE members SET role = ? WHERE team_id = ? AND id = ?",
                (TeamRole.MEMBER.value, claims.team, claims.member),
            )
            await self._db.execute(
                "UPDATE members SET role = ? WHERE team_id = ? AND id = ?",
                (TeamRole.OWNER.value, claims.team, row["id"]),
            )
        return _view(row).model_copy(update={"role": TeamRole.OWNER})

    async def _owner_only(self, claims: MemberClaims) -> None:
        """The directory decides who owns a team: a certificate may predate a hand-over."""
        async with self._db.execute(
            "SELECT role FROM members WHERE team_id = ? AND id = ?", (claims.team, claims.member)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None or row["role"] != TeamRole.OWNER.value:
            raise DirectoryError(403, "only the team owner can do that")

    async def _owned_by_account(self, account: str) -> int:
        async with self._db.execute(
            "SELECT count(*) FROM members WHERE account = ? AND role = ?",
            (account, TeamRole.OWNER.value),
        ) as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def _is_member(self, team_id: str, claims: MemberClaims) -> bool:
        async with self._db.execute(
            "SELECT 1 FROM member_keys WHERE team_id = ? AND member_id = ? AND key = ?",
            (team_id, claims.member, claims.key),
        ) as cursor:
            return await cursor.fetchone() is not None

    async def _member_count(self, team_id: str) -> int:
        async with self._db.execute(
            "SELECT count(*) FROM members WHERE team_id = ?", (team_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def _add_member(
        self,
        team_id: str,
        name: str,
        key: str,
        role: TeamRole,
        now: datetime,
        account: str | None = None,
    ) -> MemberView:
        view = MemberView(id=member_id(key), name=name, key=key, role=role, joined_at=now)
        try:
            await self._db.execute(
                "INSERT INTO members (team_id, id, name, key, role, joined_at, account)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (team_id, view.id, name, key, role.value, _iso(now), account),
            )
            await self._db.execute(
                "INSERT INTO member_keys (team_id, member_id, key, added_at) VALUES (?, ?, ?, ?)",
                (team_id, view.id, key, _iso(now)),
            )
        except aiosqlite.IntegrityError as error:
            raise DirectoryError(
                409, f"the name {name} or this key is already in the team"
            ) from error
        return view

    async def _new_invite(self, team_id: str, created_by: str) -> str:
        code = new_code()
        await self._db.execute(
            "INSERT INTO invites (hash, team_id, created_by) VALUES (?, ?, ?)",
            (code_hash(code), team_id, created_by),
        )
        return code

    def _grant(
        self,
        team_id: str,
        team_name: str,
        signer: CertSigner,
        member: MemberView,
        key: str,
        now: datetime,
        code: str | None = None,
        expires: datetime | None = None,
    ) -> TeamGrant:
        claims = MemberClaims(
            team=team_id,
            member=member.id,
            key=key,
            name=member.name,
            role=member.role,
            iat=now,
            exp=now + timedelta(seconds=self._limits.certificate_ttl_s),
        )
        return TeamGrant(
            team_id=team_id,
            team_name=team_name,
            team_key=signer.public_b64,
            certificate=signer.sign(claims),
            member=member,
            invite=code,
            invite_expires_at=expires,
        )
