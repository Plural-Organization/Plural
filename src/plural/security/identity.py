import hashlib
from datetime import datetime
from pathlib import Path
from typing import NamedTuple, Self
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
)

from plural.protocol.commands import TeamProof
from plural.protocol.team import MemberClaims
from plural.security.keys import load_or_create_host_key
from plural.security.tokens import b64decode, b64encode

AUTH_SCHEME = "Plural"


class InvalidCertificate(Exception):
    pass


class ExpiredCertificate(InvalidCertificate):
    pass


class InvalidRequest(Exception):
    pass


def public_b64(key: Ed25519PublicKey) -> str:
    return b64encode(key.public_bytes(Encoding.Raw, PublicFormat.Raw))


def member_id(key_b64: str) -> str:
    return f"m_{hashlib.sha256(b64decode(key_b64)).hexdigest()[:16]}"


def valid_public_key(key_b64: str) -> bool:
    try:
        raw = b64decode(key_b64)
        Ed25519PublicKey.from_public_bytes(raw)
    except ValueError:
        return False
    return len(raw) == 32


class Identity:
    def __init__(self, key: Ed25519PrivateKey) -> None:
        self._key = key

    @classmethod
    def load_or_create(cls, path: Path) -> Self:
        return cls(load_or_create_host_key(path))

    @property
    def public_b64(self) -> str:
        return public_b64(self._key.public_key())

    @property
    def member_id(self) -> str:
        return member_id(self.public_b64)

    def sign(self, message: bytes) -> str:
        return b64encode(self._key.sign(message))


def verify_signature(key_b64: str, message: bytes, signature: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(b64decode(key_b64)).verify(b64decode(signature), message)
    except (ValueError, InvalidSignature):
        return False
    return True


class CertSigner:
    def __init__(self, key: Ed25519PrivateKey) -> None:
        self._key = key

    @classmethod
    def generate(cls) -> Self:
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_pem(cls, pem: bytes) -> Self:
        key = load_pem_private_key(pem, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("not an Ed25519 private key")
        return cls(key)

    def to_pem(self) -> bytes:
        return self._key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())

    @property
    def public_b64(self) -> str:
        return public_b64(self._key.public_key())

    def sign(self, claims: MemberClaims) -> str:
        body = claims.model_dump_json().encode()
        return f"{b64encode(body)}.{b64encode(self._key.sign(body))}"


class CertVerifier:
    def __init__(self, team_key_b64: str) -> None:
        self._team_key = team_key_b64

    def verify(self, certificate: str, *, now: datetime) -> MemberClaims:
        try:
            body_b64, signature = certificate.split(".")
            body = b64decode(body_b64)
            if not verify_signature(self._team_key, body, signature):
                raise InvalidCertificate("forged certificate")
            claims = MemberClaims.model_validate_json(body)
        except ValueError as error:
            raise InvalidCertificate("malformed certificate") from error
        if claims.exp <= now:
            raise ExpiredCertificate("certificate expired")
        return claims


class SignedRequest(NamedTuple):
    certificate: str
    timestamp: int
    nonce: str
    signature: str


def request_message(method: str, path: str, body: bytes, timestamp: int, nonce: str) -> bytes:
    digest = hashlib.sha256(body).hexdigest()
    return f"{method.upper()}\n{path}\n{timestamp}\n{nonce}\n{digest}".encode()


def authorization(
    identity: Identity,
    certificate: str,
    method: str,
    path: str,
    body: bytes,
    *,
    timestamp: int,
    nonce: str,
) -> str:
    signature = identity.sign(request_message(method, path, body, timestamp, nonce))
    return f"{AUTH_SCHEME} cert={certificate} ts={timestamp} nonce={nonce} sig={signature}"


def parse_authorization(header: str | None) -> SignedRequest:
    if header is None or not header.startswith(f"{AUTH_SCHEME} "):
        raise InvalidRequest("this needs a signed request")
    fields = dict(
        part.split("=", 1) for part in header[len(AUTH_SCHEME) + 1 :].split(" ") if "=" in part
    )
    try:
        return SignedRequest(
            certificate=fields["cert"],
            timestamp=int(fields["ts"]),
            nonce=fields["nonce"],
            signature=fields["sig"],
        )
    except (KeyError, ValueError) as error:
        raise InvalidRequest("malformed authorization") from error


def verify_request(
    signed: SignedRequest, claims: MemberClaims, method: str, path: str, body: bytes
) -> bool:
    message = request_message(method, path, body, signed.timestamp, signed.nonce)
    return verify_signature(claims.key, message, signed.signature)


def join_message(url: str, room: str, timestamp: int, nonce: str) -> bytes:
    return f"plural-team-join\n{url}\n{room}\n{timestamp}\n{nonce}".encode()


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    port = parts.port
    default = {"ws": 80, "wss": 443, "http": 80, "https": 443}.get(parts.scheme)
    host = (parts.hostname or "").lower()
    netloc = host if port is None or port == default else f"{host}:{port}"
    return f"{parts.scheme.lower()}://{netloc}{parts.path.rstrip('/')}"


def build_team_proof(
    identity: Identity,
    certificate: str,
    url: str,
    room: str,
    *,
    timestamp: int,
    nonce: str,
) -> TeamProof:
    return TeamProof(
        certificate=certificate,
        url=url,
        ts=timestamp,
        nonce=nonce,
        proof=identity.sign(join_message(url, room, timestamp, nonce)),
    )


def verify_team_proof(proof: TeamProof, claims: MemberClaims, room: str) -> bool:
    message = join_message(proof.url, room, proof.ts, proof.nonce)
    return verify_signature(claims.key, message, proof.proof)
