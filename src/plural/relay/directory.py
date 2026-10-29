import asyncio
import hashlib
import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Self

import aiosqlite

from plural.protocol.team import (
    Invite,
    MemberClaims,
    MemberList,
    MemberView,
    Renewed,
    TeamCreate,
    TeamGrant,
    TeamJoin,
    TeamRole,
)
from plural.security.identity import (
    CertSigner,
    CertVerifier,
    InvalidCertificate,
    InvalidRequest,
    member_id,
    parse_authorization,
    valid_public_key,
    verify_request,
)

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
    PRIMARY KEY (team_id, id)
);
CREATE UNIQUE INDEX IF NOT EXISTS members_name ON members (team_id, lower(name));
CREATE TABLE IF NOT EXISTS invites (
    hash TEXT PRIMARY KEY,
    team_id TEXT NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    created_by TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_by TEXT
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
    max_members: int = 50
    invite_ttl_s: int = 3600
    certificate_ttl_s: int = 30 * 86_400
    clock_skew_s: int = 60


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
    ) -> None:
        self._db = db
        self._limits = limits or TeamLimits()
        self._clock = clock
        self._seen: dict[str, datetime] = {}
        self._writing = asyncio.Lock()

    @classmethod
    async def open(
        cls,
        path: Path,
        *,
        limits: TeamLimits | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> Self:
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.close(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600))
        db = await aiosqlite.connect(path)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        await db.executescript(SCHEMA)
        await db.commit()
        return cls(db, limits=limits, clock=clock)

    async def close(self) -> None:
        await self._db.close()

    async def team_count(self) -> int:
        async with self._db.execute("SELECT count(*) FROM teams") as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def create(self, request: TeamCreate) -> TeamGrant:
        async with self._writing:
            if not valid_public_key(request.key):
                raise DirectoryError(400, "that is not a public key")
            if await self.team_count() >= self._limits.max_teams:
                raise DirectoryError(429, "this relay cannot take more teams")
            now = self._clock()
            signer = CertSigner.generate()
            team_id = f"t_{secrets.token_hex(8)}"
            await self._db.execute(
                "INSERT INTO teams (id, name, signing_key, public_key, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (team_id, request.name, signer.to_pem(), signer.public_b64, _iso(now)),
            )
            try:
                member = await self._add_member(
                    team_id, request.member_name, request.key, TeamRole.OWNER, now
                )
                code, expires = await self._new_invite(team_id, member.id, now)
            except DirectoryError:
                await self._db.rollback()
                raise
            await self._db.commit()
            return self._grant(
                team_id, request.name, signer, member, request.key, now, code, expires
            )

    async def join(self, request: TeamJoin) -> TeamGrant:
        async with self._writing:
            if not valid_public_key(request.key):
                raise DirectoryError(400, "that is not a public key")
            now = self._clock()
            async with self._db.execute(
                "SELECT i.team_id, i.expires_at, i.used_by, t.name, t.signing_key"
                " FROM invites i JOIN teams t ON t.id = i.team_id WHERE i.hash = ?",
                (code_hash(request.code),),
            ) as cursor:
                row = await cursor.fetchone()
            if (
                row is None
                or row["used_by"] is not None
                or datetime.fromisoformat(row["expires_at"]) <= now
            ):
                raise DirectoryError(403, "that invite code is wrong, used or expired")
            team_id: str = row["team_id"]
            if await self._member_count(team_id) >= self._limits.max_members:
                raise DirectoryError(409, "this team is full")
            claimed = await self._db.execute(
                "UPDATE invites SET used_by = ? WHERE hash = ? AND used_by IS NULL",
                (member_id(request.key), code_hash(request.code)),
            )
            if claimed.rowcount != 1:
                raise DirectoryError(403, "that invite code is wrong, used or expired")
            try:
                member = await self._add_member(
                    team_id, request.name, request.key, TeamRole.MEMBER, now
                )
            except DirectoryError:
                await self._db.rollback()
                raise
            await self._db.commit()
            signer = CertSigner.from_pem(row["signing_key"])
            return self._grant(team_id, row["name"], signer, member, request.key, now)

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
        except InvalidCertificate as error:
            if "expired" in str(error):
                raise DirectoryError(
                    401, "your team certificate has expired, ask the owner for a new invite"
                ) from error
            raise denied from error
        if claims.team != team_id or not await self._is_member(team_id, claims):
            raise denied
        if abs(int(now.timestamp()) - signed.timestamp) > self._limits.clock_skew_s:
            raise DirectoryError(401, "your clock is off by more than a minute")
        if not verify_request(signed, claims, method, path, body):
            raise denied
        key = f"{claims.member}:{signed.nonce}"
        self._forget_old(now)
        if key in self._seen:
            raise DirectoryError(401, "this request was already used")
        self._seen[key] = now
        return claims

    async def still_valid(self, claims: MemberClaims) -> bool:
        return claims.exp > self._clock() and await self._is_member(claims.team, claims)

    async def members(self, claims: MemberClaims) -> MemberList:
        async with self._db.execute(
            "SELECT name FROM teams WHERE id = ?", (claims.team,)
        ) as cursor:
            team = await cursor.fetchone()
        async with self._db.execute(
            "SELECT id, name, key, role, joined_at FROM members WHERE team_id = ?"
            " ORDER BY (role = 'owner') DESC, joined_at, name",
            (claims.team,),
        ) as cursor:
            rows = await cursor.fetchall()
        return MemberList(
            team_id=claims.team,
            team_name=team["name"] if team else "",
            members=tuple(_view(row) for row in rows),
        )

    async def invite(self, claims: MemberClaims) -> Invite:
        async with self._writing:
            self._owner_only(claims)
            if await self._member_count(claims.team) >= self._limits.max_members:
                raise DirectoryError(409, "this team is full")
            code, expires = await self._new_invite(claims.team, claims.member, self._clock())
            await self._db.commit()
            return Invite(code=code, expires_at=expires)

    async def remove(self, claims: MemberClaims, target: str) -> MemberView:
        async with self._writing:
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
                self._owner_only(claims)
            if view.role is TeamRole.OWNER:
                raise DirectoryError(409, "the owner cannot leave; disband the team instead")
            await self._db.execute(
                "DELETE FROM members WHERE team_id = ? AND id = ?", (claims.team, view.id)
            )
            await self._db.commit()
            return view

    async def disband(self, claims: MemberClaims) -> None:
        async with self._writing:
            self._owner_only(claims)
            await self._db.execute("DELETE FROM teams WHERE id = ?", (claims.team,))
            await self._db.commit()

    async def renew(self, claims: MemberClaims) -> Renewed:
        async with self._db.execute(
            "SELECT signing_key FROM teams WHERE id = ?", (claims.team,)
        ) as cursor:
            team = await cursor.fetchone()
        if team is None:
            raise DirectoryError(404, "this team is gone")
        now = self._clock()
        fresh = claims.model_copy(
            update={"iat": now, "exp": now + timedelta(seconds=self._limits.certificate_ttl_s)}
        )
        return Renewed(certificate=CertSigner.from_pem(team["signing_key"]).sign(fresh))

    def _owner_only(self, claims: MemberClaims) -> None:
        if claims.role is not TeamRole.OWNER:
            raise DirectoryError(403, "only the team owner can do that")

    def _forget_old(self, now: datetime) -> None:
        horizon = now - timedelta(seconds=2 * self._limits.clock_skew_s)
        for key in [key for key, seen in self._seen.items() if seen < horizon]:
            del self._seen[key]

    async def _is_member(self, team_id: str, claims: MemberClaims) -> bool:
        async with self._db.execute(
            "SELECT 1 FROM members WHERE team_id = ? AND id = ? AND key = ?",
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
        self, team_id: str, name: str, key: str, role: TeamRole, now: datetime
    ) -> MemberView:
        view = MemberView(id=member_id(key), name=name, key=key, role=role, joined_at=now)
        try:
            await self._db.execute(
                "INSERT INTO members (team_id, id, name, key, role, joined_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (team_id, view.id, name, key, role.value, _iso(now)),
            )
        except aiosqlite.IntegrityError as error:
            raise DirectoryError(
                409, f"the name {name} or this key is already in the team"
            ) from error
        return view

    async def _new_invite(
        self, team_id: str, created_by: str, now: datetime
    ) -> tuple[str, datetime]:
        code = new_code()
        expires = now + timedelta(seconds=self._limits.invite_ttl_s)
        await self._db.execute(
            "INSERT INTO invites (hash, team_id, created_by, expires_at) VALUES (?, ?, ?, ?)",
            (code_hash(code), team_id, created_by, _iso(expires)),
        )
        return code, expires

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
