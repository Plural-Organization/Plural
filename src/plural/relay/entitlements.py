from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum

import structlog

from plural.protocol.entitlement import EntitlementClaims
from plural.protocol.relay import RelayOpen
from plural.security.accounts_key import REFRESH_S, RETRY_S, AccountsKey
from plural.security.entitlement import EntitlementVerifier, InvalidEntitlement, fetch_verifier

log = structlog.get_logger(__name__)


class Outcome(StrEnum):
    NONE = "none"  # the host sent no certificate
    VALID = "valid"
    EXPIRED = "expired"
    FORGED = "forged"  # not signed by the accounts service (or its key rotated)
    MALFORMED = "malformed"
    OTHER_KEY = "other_key"  # a genuine certificate for a different host key
    UNVERIFIED = "unverified"  # the accounts key is not known yet


def utcnow() -> datetime:
    return datetime.now(UTC)


class EntitlementWatch:
    """Looks at the certificate a host opens a room with and says what it found. Never refuses.

    The relay learns who is connecting without turning anyone away, so a policy can be chosen
    from what the log shows before any host is affected. Checking is CPU only: the accounts key
    is read in the background, and a host that opens before it arrives is counted `unverified`.
    """

    def __init__(
        self,
        accounts_url: str,
        *,
        fetch: Callable[[str], EntitlementVerifier] = fetch_verifier,
        now: Callable[[], datetime] = utcnow,
        refresh_s: float = REFRESH_S,
        retry_s: float = RETRY_S,
    ) -> None:
        self._key = AccountsKey(accounts_url, fetch=fetch, refresh_s=refresh_s, retry_s=retry_s)
        self._now = now
        self.counts: Counter[str] = Counter()

    @property
    def ready(self) -> bool:
        """Whether the accounts key is known, so a certificate can be judged."""
        return self._key.ready

    def start(self) -> None:
        self._key.start()

    async def stop(self) -> None:
        await self._key.stop()

    def check(self, opening: RelayOpen) -> tuple[Outcome, EntitlementClaims | None]:
        outcome, claims = self._classify(opening)
        self.counts[outcome.value] += 1
        return outcome, claims

    def _classify(self, opening: RelayOpen) -> tuple[Outcome, EntitlementClaims | None]:
        if opening.entitlement is None:
            return Outcome.NONE, None
        verifier = self._key.verifier
        if verifier is None:
            return Outcome.UNVERIFIED, None
        try:
            claims = verifier.verify(opening.entitlement, now=self._now())
        except InvalidEntitlement as error:
            if error.reason == "forged":
                # A rotated key looks like a forgery: read the key again, soon.
                self._key.suspect()
            return Outcome(error.reason), None
        if claims.key != opening.public_key:
            return Outcome.OTHER_KEY, claims
        return Outcome.VALID, claims
