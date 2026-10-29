from datetime import datetime
from enum import StrEnum
from typing import Annotated

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
    role: TeamRole
    joined_at: datetime


class TeamCreate(Model):
    name: TeamName
    member_name: MemberName
    key: str


class TeamJoin(Model):
    code: str = Field(min_length=4, max_length=64)
    name: MemberName
    key: str


class TeamGrant(Model):
    team_id: str
    team_name: str
    team_key: str
    certificate: str
    member: MemberView
    invite: str | None = None
    invite_expires_at: datetime | None = None


class Invite(Model):
    code: str
    expires_at: datetime


class MemberList(Model):
    team_id: str
    team_name: str
    members: tuple[MemberView, ...]


class Renewed(Model):
    certificate: str
