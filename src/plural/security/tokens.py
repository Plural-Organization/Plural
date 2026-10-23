import base64
from datetime import datetime
from typing import Self

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from plural.protocol.capability import CapabilityClaims


class InvalidToken(Exception):
    pass


class TokenVerifier:
    def __init__(self, key: Ed25519PublicKey) -> None:
        self._key = key

    @classmethod
    def from_b64(cls, raw: str) -> Self:
        return cls(Ed25519PublicKey.from_public_bytes(b64decode(raw)))

    def public_b64(self) -> str:
        return b64encode(self._key.public_bytes(Encoding.Raw, PublicFormat.Raw))

    def verify(self, token: str, *, now: datetime) -> CapabilityClaims:
        try:
            body_b64, signature_b64 = token.split(".")
            body = b64decode(body_b64)
            self._key.verify(b64decode(signature_b64), body)
            claims = CapabilityClaims.model_validate_json(body)
        except (ValueError, InvalidSignature) as error:
            raise InvalidToken("malformed or forged token") from error
        if claims.exp <= now:
            raise InvalidToken("token expired")
        return claims

    def verify_proof(self, message: bytes, proof: str) -> bool:
        try:
            self._key.verify(b64decode(proof), message)
        except (ValueError, InvalidSignature):
            return False
        return True


class TokenSigner:
    def __init__(self, key: Ed25519PrivateKey) -> None:
        self._key = key
        self.verifier = TokenVerifier(key.public_key())

    def sign(self, claims: CapabilityClaims) -> str:
        body = claims.model_dump_json().encode()
        return f"{b64encode(body)}.{b64encode(self._key.sign(body))}"

    def prove(self, message: bytes) -> str:
        return b64encode(self._key.sign(message))


def b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
