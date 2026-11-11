import base64
import json
import urllib.request
from datetime import datetime
from typing import Literal, Self

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import ValidationError

from plural.protocol.entitlement import EntitlementClaims
from plural.protocol.ticket import TicketClaims

KEY_PATH = "/.well-known/entitlement-key"
FETCH_TIMEOUT_S = 5.0


def b64decode(data: str) -> bytes:
    """Base64url without padding that refuses stray characters, so junk reads as malformed."""
    padded = data.replace("-", "+").replace("_", "/") + "=" * (-len(data) % 4)
    return base64.b64decode(padded, validate=True)


class InvalidEntitlement(Exception):
    def __init__(self, reason: Literal["malformed", "forged", "expired", "wrong_audience"]) -> None:
        super().__init__(reason)
        self.reason = reason


class EntitlementVerifier:
    """Checks what an accounts service signed (a certificate or a ticket) against its public key."""

    def __init__(self, key: Ed25519PublicKey) -> None:
        self._key = key

    @classmethod
    def from_b64(cls, raw: str) -> Self:
        return cls(Ed25519PublicKey.from_public_bytes(b64decode(raw)))

    def _body(self, signed: str) -> bytes:
        try:
            body_b64, signature_b64 = signed.split(".")
            body = b64decode(body_b64)
            signature = b64decode(signature_b64)
        except ValueError as error:
            raise InvalidEntitlement("malformed") from error
        try:
            self._key.verify(signature, body)
        except InvalidSignature as error:
            raise InvalidEntitlement("forged") from error
        return body

    def verify(self, certificate: str, *, now: datetime) -> EntitlementClaims:
        body = self._body(certificate)
        try:
            claims = EntitlementClaims.model_validate_json(body)
        except ValidationError as error:
            raise InvalidEntitlement("malformed") from error
        if claims.exp <= now:
            raise InvalidEntitlement("expired")
        return claims

    def ticket(
        self, ticket: str, *, now: datetime, audience: Literal["daemon", "teams"]
    ) -> TicketClaims:
        """A ticket for this receiver: one meant for another receiver is refused."""
        body = self._body(ticket)
        try:
            claims = TicketClaims.model_validate_json(body)
        except ValidationError as error:
            raise InvalidEntitlement("malformed") from error
        if claims.aud != audience:
            raise InvalidEntitlement("wrong_audience")
        if claims.exp <= now:
            raise InvalidEntitlement("expired")
        return claims


def fetch_verifier(base_url: str) -> EntitlementVerifier:
    """Reads an accounts service's public key, blocking: run it off the event loop."""
    request = urllib.request.Request(
        base_url.rstrip("/") + KEY_PATH, headers={"user-agent": "plural"}
    )
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_S) as response:
        body = json.load(response)
    if body.get("version") != 1:
        raise ValueError("unsupported entitlement key version")
    return EntitlementVerifier.from_b64(str(body["key"]))
