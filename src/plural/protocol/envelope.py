from datetime import datetime
from enum import StrEnum
from typing import Final

from pydantic import Field, JsonValue

from plural.protocol.models import Model

PROTOCOL_VERSION: Final = 1


class Kind(StrEnum):
    CMD = "cmd"
    EVT = "evt"
    ACK = "ack"


class ErrorCode(StrEnum):
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    INVALID = "invalid"
    CONFLICT = "conflict"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    VERSION_MISMATCH = "version_mismatch"
    INTERNAL = "internal"


class ErrorInfo(Model):
    code: ErrorCode
    message: str


class Envelope(Model):
    v: int = PROTOCOL_VERSION
    id: str
    kind: Kind
    type: str | None = None
    room: str
    ts: datetime
    actor: str | None = None
    seq: int | None = None
    to: str | None = None
    token: str | None = None
    re: str | None = None
    ok: bool | None = None
    error: ErrorInfo | None = None
    payload: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
