import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from plural.protocol.entitlement import EntitlementClaims
from plural.protocol.relay import RelayOpen
from plural.relay.entitlements import EntitlementWatch, Outcome
from plural.security.entitlement import EntitlementVerifier, InvalidEntitlement
from plural.security.tokens import TokenSigner, b64encode

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


class Accounts:
    """Stands in for the accounts service: signs certificates with its own key."""

    def __init__(self) -> None:
        self.key = Ed25519PrivateKey.generate()
        self.verifier = EntitlementVerifier(self.key.public_key())

    def certificate(self, host_key: str, *, expires: timedelta = timedelta(days=14)) -> str:
        claims = EntitlementClaims(account="a_1", key=host_key, iat=NOW, exp=NOW + expires)
        body = claims.model_dump_json().encode()
        return f"{b64encode(body)}.{b64encode(self.key.sign(body))}"


def opening(certificate: str | None, host: TokenSigner | None = None) -> RelayOpen:
    host = host or TokenSigner(Ed25519PrivateKey.generate())
    return RelayOpen(
        room="r_1",
        public_key=host.verifier.public_b64(),
        proof=host.prove(b"r_1"),
        entitlement=certificate,
    )


async def watching(accounts: Accounts) -> EntitlementWatch:
    watch = EntitlementWatch(
        "https://accounts.example", fetch=lambda _: accounts.verifier, now=lambda: NOW
    )
    watch.start()
    async with asyncio.timeout(5):
        while not watch.ready:
            await asyncio.sleep(0.01)
    return watch


def test_a_certificate_is_judged_offline() -> None:
    accounts = Accounts()
    host = TokenSigner(Ed25519PrivateKey.generate())
    key = host.verifier.public_b64()
    claims = accounts.verifier.verify(accounts.certificate(key), now=NOW)
    assert (claims.account, claims.key) == ("a_1", key)
    with pytest.raises(InvalidEntitlement) as expired:
        accounts.verifier.verify(accounts.certificate(key, expires=timedelta(seconds=-1)), now=NOW)
    assert expired.value.reason == "expired"
    with pytest.raises(InvalidEntitlement) as forged:
        Accounts().verifier.verify(accounts.certificate(key), now=NOW)
    assert forged.value.reason == "forged"
    for junk in ("", "x", "a.b.c", "!!.!!"):
        with pytest.raises(InvalidEntitlement) as malformed:
            accounts.verifier.verify(junk, now=NOW)
        assert malformed.value.reason == "malformed"


async def test_each_kind_of_host_is_told_apart() -> None:
    accounts = Accounts()
    watch = await watching(accounts)
    try:
        host = TokenSigner(Ed25519PrivateKey.generate())
        key = host.verifier.public_b64()
        other = TokenSigner(Ed25519PrivateKey.generate()).verifier.public_b64()
        cases = {
            Outcome.NONE: opening(None),
            Outcome.VALID: opening(accounts.certificate(key), host),
            Outcome.EXPIRED: opening(accounts.certificate(key, expires=timedelta(days=-1)), host),
            Outcome.FORGED: opening(Accounts().certificate(key), host),
            Outcome.MALFORMED: opening("not a certificate", host),
            Outcome.OTHER_KEY: opening(accounts.certificate(other), host),
        }
        for expected, request in cases.items():
            outcome, claims = watch.check(request)
            assert outcome is expected
            assert (claims is not None) is (expected in (Outcome.VALID, Outcome.OTHER_KEY))
        assert dict(watch.counts) == {outcome.value: 1 for outcome in cases}
    finally:
        await watch.stop()


async def test_a_certificate_cannot_be_judged_before_the_key_arrives() -> None:
    def unreachable(_: str) -> EntitlementVerifier:
        raise OSError("accounts is down")

    watch = EntitlementWatch("https://accounts.example", fetch=unreachable, retry_s=60)
    watch.start()
    try:
        await asyncio.sleep(0.05)
        assert not watch.ready
        assert watch.check(opening("anything"))[0] is Outcome.UNVERIFIED
        assert watch.check(opening(None))[0] is Outcome.NONE
    finally:
        await watch.stop()


async def test_the_key_is_read_again_when_a_certificate_looks_forged() -> None:
    old, new = Accounts(), Accounts()
    reads: list[EntitlementVerifier] = [old.verifier, new.verifier]
    watch = EntitlementWatch(
        "https://accounts.example",
        fetch=lambda _: reads.pop(0) if len(reads) > 1 else reads[0],
        now=lambda: NOW,
        retry_s=0,
    )
    watch.start()
    try:
        async with asyncio.timeout(5):
            while not watch.ready:
                await asyncio.sleep(0.01)
        host = TokenSigner(Ed25519PrivateKey.generate())
        request = opening(new.certificate(host.verifier.public_b64()), host)
        assert watch.check(request)[0] is Outcome.FORGED
        async with asyncio.timeout(5):
            while watch.check(request)[0] is not Outcome.VALID:
                await asyncio.sleep(0.01)
    finally:
        await watch.stop()
