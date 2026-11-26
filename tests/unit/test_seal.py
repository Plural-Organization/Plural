from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from plural.protocol.capability import SuccessionClaims
from plural.security.seal import SealError, SealKey, seal
from plural.security.succession import (
    STATEMENT_TTL,
    InvalidSuccession,
    sign_succession,
    verify_succession,
)
from plural.security.tokens import TokenSigner

NOW = datetime(2026, 11, 26, tzinfo=UTC)


def test_a_sealed_blob_opens_only_for_its_recipient() -> None:
    mine, other = SealKey(), SealKey()
    sealed = seal(mine.public_b64, b"the whole session")
    assert b"the whole session" not in sealed
    assert mine.open(sealed) == b"the whole session"
    with pytest.raises(SealError):
        other.open(sealed)


def test_a_changed_or_short_blob_is_refused() -> None:
    key = SealKey()
    sealed = bytearray(seal(key.public_b64, b"x" * 100))
    sealed[-1] ^= 1
    with pytest.raises(SealError):
        key.open(bytes(sealed))
    with pytest.raises(SealError):
        key.open(b"short")
    with pytest.raises(SealError):
        seal("not a key", b"x")


def test_two_seals_of_the_same_text_differ() -> None:
    key = SealKey()
    assert seal(key.public_b64, b"same") != seal(key.public_b64, b"same")


def statement(
    old: TokenSigner, new: TokenSigner, *, room: str = "r_1", ttl: timedelta = STATEMENT_TTL
) -> str:
    claims = SuccessionClaims(
        room=room,
        from_key=old.verifier.public_b64(),
        to_key=new.verifier.public_b64(),
        last_seq=42,
        iat=NOW,
        exp=NOW + ttl,
    )
    return sign_succession(old, claims)


def check(text: str, old: TokenSigner, new: TokenSigner, *, room: str = "r_1") -> SuccessionClaims:
    return verify_succession(
        text,
        room=room,
        current_key=old.verifier.public_b64(),
        new_key=new.verifier.public_b64(),
        now=NOW,
    )


def test_a_succession_is_believed_when_the_room_key_signed_it_for_this_successor() -> None:
    old, new = TokenSigner(Ed25519PrivateKey.generate()), TokenSigner(Ed25519PrivateKey.generate())
    assert check(statement(old, new), old, new).last_seq == 42


def test_a_succession_is_refused_for_the_wrong_signer_room_successor_or_time() -> None:
    old, new, third = (TokenSigner(Ed25519PrivateKey.generate()) for _ in range(3))
    with pytest.raises(InvalidSuccession):
        check(statement(third, new), old, new)  # not signed by the room's key
    with pytest.raises(InvalidSuccession):
        check(statement(old, new), old, third)  # made for someone else
    with pytest.raises(InvalidSuccession):
        check(statement(old, new), old, new, room="r_2")  # another room
    with pytest.raises(InvalidSuccession):
        check(statement(old, new, ttl=timedelta(seconds=-1)), old, new)  # lapsed
    with pytest.raises(InvalidSuccession):
        check("garbage", old, new)
