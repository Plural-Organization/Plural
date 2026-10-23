from datetime import UTC, datetime, timedelta
from pathlib import PurePath

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from plural.protocol.capability import CapabilityClaims
from plural.protocol.models import Role
from plural.security.secrets import Redactor, is_denied_path
from plural.security.tokens import InvalidToken, TokenSigner

NOW = datetime(2026, 10, 22, tzinfo=UTC)


def claims(ttl: timedelta = timedelta(hours=1)) -> CapabilityClaims:
    return CapabilityClaims(
        room="r_1", participant="p_1", role=Role.PARTICIPANT, iat=NOW, exp=NOW + ttl, jti="t_1"
    )


def test_token_roundtrip() -> None:
    signer = TokenSigner(Ed25519PrivateKey.generate())
    assert signer.verifier.verify(signer.sign(claims()), now=NOW) == claims()


def test_token_rejects_forgery_and_expiry() -> None:
    signer = TokenSigner(Ed25519PrivateKey.generate())
    other = TokenSigner(Ed25519PrivateKey.generate())
    with pytest.raises(InvalidToken):
        signer.verifier.verify(other.sign(claims()), now=NOW)
    with pytest.raises(InvalidToken):
        signer.verifier.verify(signer.sign(claims(timedelta(seconds=-1))), now=NOW)
    with pytest.raises(InvalidToken):
        signer.verifier.verify("garbage", now=NOW)


def test_relay_proof() -> None:
    signer = TokenSigner(Ed25519PrivateKey.generate())
    proof = signer.prove(b"r_1")
    assert signer.verifier.verify_proof(b"r_1", proof)
    assert not signer.verifier.verify_proof(b"r_2", proof)


def test_redaction() -> None:
    redactor = Redactor.from_environment({"ANTHROPIC_API_KEY": "super-secret-value", "HOME": "/x"})
    text = redactor.redact("key=super-secret-value token=sk-ant-abcdefghijklmnopqrstuv home=/x")
    assert "super-secret-value" not in text
    assert "sk-ant-" not in text
    assert "home=/x" in text


@pytest.mark.parametrize(
    ("path", "denied"),
    [
        (".env", True),
        ("app/.env.local", True),
        ("keys/id_ed25519", True),
        (".ssh/config", True),
        ("src/main.py", False),
        (".git/config", True),
    ],
)
def test_denied_paths(path: str, denied: bool) -> None:
    assert is_denied_path(PurePath(path)) is denied
