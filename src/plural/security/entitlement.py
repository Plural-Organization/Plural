import base64
from datetime import datetime
from typing import Literal, Self

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import ValidationError

from plural.protocol.entitlement import EntitlementClaims


def b64decode(data: str) -> bytes:
    """Base64url without padding that refuses stray characters, so junk reads as malformed."""
    return base64.b64decode(
        data.replace("-", "+").replace("_", "/") + "=" * (-len(data) % 4), validate=True
    )


class InvalidEntitlement(Exception):
    def __init__(self, reason: Literal["malformed", "forged", "expired"]) -> None:
        super().__init__(reason)
        self.reason = reason


class EntitlementVerifier:
    """Checks a certificate from an accounts service against that service's public key, offline."""

    def __init__(self, key: Ed25519PublicKey) -> None:
        self._key = key

    @classmethod
    def from_b64(cls, raw: str) -> Self:
        return cls(Ed25519PublicKey.from_public_bytes(b64decode(raw)))

    def verify(self, certificate: str, *, now: datetime) -> EntitlementClaims:
        try:
            body_b64, signature_b64 = certificate.split(".")
            body = b64decode(body_b64)
            signature = b64decode(signature_b64)
        except ValueError as error:
            raise InvalidEntitlement("malformed") from error
        try:
            self._key.verify(signature, body)
        except InvalidSignature as error:
            raise InvalidEntitlement("forged") from error
        try:
            claims = EntitlementClaims.model_validate_json(body)
        except ValidationError as error:
            raise InvalidEntitlement("malformed") from error
        if claims.exp <= now:
            raise InvalidEntitlement("expired")
        return claims
