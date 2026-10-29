from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from plural.protocol.team import MemberClaims, TeamRole
from plural.security.identity import (
    CertSigner,
    CertVerifier,
    Identity,
    InvalidCertificate,
    InvalidRequest,
    authorization,
    member_id,
    parse_authorization,
    valid_public_key,
    verify_request,
)

NOW = datetime(2026, 10, 29, tzinfo=UTC)


def claims_for(identity: Identity, ttl: timedelta = timedelta(days=30)) -> MemberClaims:
    return MemberClaims(
        team="t_1",
        member=identity.member_id,
        key=identity.public_b64,
        name="alia",
        role=TeamRole.MEMBER,
        iat=NOW,
        exp=NOW + ttl,
    )


def test_a_certificate_round_trips_under_the_team_key() -> None:
    signer = CertSigner.generate()
    alia = Identity(Ed25519PrivateKey.generate())
    certificate = signer.sign(claims_for(alia))
    assert CertVerifier(signer.public_b64).verify(certificate, now=NOW) == claims_for(alia)


def test_a_certificate_from_another_team_is_forged() -> None:
    alia = Identity(Ed25519PrivateKey.generate())
    certificate = CertSigner.generate().sign(claims_for(alia))
    with pytest.raises(InvalidCertificate):
        CertVerifier(CertSigner.generate().public_b64).verify(certificate, now=NOW)


def test_a_certificate_whose_claims_were_edited_is_forged() -> None:
    signer = CertSigner.generate()
    alia = Identity(Ed25519PrivateKey.generate())
    body, signature = signer.sign(claims_for(alia)).split(".")
    owner = claims_for(alia).model_copy(update={"role": TeamRole.OWNER})
    forged = signer.sign(owner).split(".")[0]
    with pytest.raises(InvalidCertificate):
        CertVerifier(signer.public_b64).verify(f"{forged}.{signature}", now=NOW)
    assert body != forged


def test_an_expired_or_malformed_certificate_is_refused() -> None:
    signer = CertSigner.generate()
    alia = Identity(Ed25519PrivateKey.generate())
    verifier = CertVerifier(signer.public_b64)
    with pytest.raises(InvalidCertificate, match="expired"):
        verifier.verify(
            signer.sign(claims_for(alia, timedelta(days=1))), now=NOW + timedelta(days=2)
        )
    for junk in ["", "abc", "a.b.c", "!!!.???"]:
        with pytest.raises(InvalidCertificate):
            verifier.verify(junk, now=NOW)


def test_the_team_key_survives_being_stored() -> None:
    signer = CertSigner.generate()
    again = CertSigner.from_pem(signer.to_pem())
    assert again.public_b64 == signer.public_b64


def test_a_request_is_bound_to_its_method_path_body_and_key() -> None:
    alia = Identity(Ed25519PrivateKey.generate())
    bek = Identity(Ed25519PrivateKey.generate())
    claims = claims_for(alia)
    header = authorization(
        alia, "cert", "POST", "/teams/t_1/invites", b"{}", timestamp=100, nonce="n1"
    )
    signed = parse_authorization(header)
    assert verify_request(signed, claims, "POST", "/teams/t_1/invites", b"{}")
    assert not verify_request(signed, claims, "GET", "/teams/t_1/invites", b"{}")
    assert not verify_request(signed, claims, "POST", "/teams/t_2/invites", b"{}")
    assert not verify_request(signed, claims, "POST", "/teams/t_1/invites", b"{ }")
    assert not verify_request(signed, claims_for(bek), "POST", "/teams/t_1/invites", b"{}")


def test_a_missing_or_garbled_authorization_is_refused() -> None:
    for header in [None, "", "Bearer x", "Plural cert=a", "Plural cert=a ts=x nonce=n sig=s"]:
        with pytest.raises(InvalidRequest):
            parse_authorization(header)


def test_an_identity_is_created_once_and_keeps_its_id(tmp_path: Path) -> None:
    path = tmp_path / "identity.pem"
    first = Identity.load_or_create(path)
    again = Identity.load_or_create(path)
    assert first.public_b64 == again.public_b64
    assert first.member_id == again.member_id == member_id(first.public_b64)
    assert path.stat().st_mode & 0o777 == 0o600


def test_only_a_real_public_key_is_accepted() -> None:
    assert valid_public_key(Identity(Ed25519PrivateKey.generate()).public_b64)
    assert not valid_public_key("not a key")
    assert not valid_public_key("AAAA")
