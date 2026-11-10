import asyncio
import json
import urllib.request
from collections import Counter
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from enum import StrEnum

import structlog

from plural.protocol.entitlement import EntitlementClaims
from plural.protocol.relay import RelayOpen
from plural.security.entitlement import EntitlementVerifier, InvalidEntitlement

log = structlog.get_logger(__name__)

KEY_PATH = "/.well-known/entitlement-key"
REFRESH_S = 3600.0
RETRY_S = 30.0
FETCH_TIMEOUT_S = 5.0


class Outcome(StrEnum):
    NONE = "none"  # the host sent no certificate
    VALID = "valid"
    EXPIRED = "expired"
    FORGED = "forged"  # not signed by the accounts service (or its key rotated)
    MALFORMED = "malformed"
    OTHER_KEY = "other_key"  # a genuine certificate for a different host key
    UNVERIFIED = "unverified"  # the accounts key is not known yet


def fetch_key(base_url: str) -> EntitlementVerifier:
    """Reads the accounts service's public key, blocking: run it off the event loop."""
    request = urllib.request.Request(
        base_url.rstrip("/") + KEY_PATH, headers={"user-agent": "plural-relay"}
    )
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_S) as response:
        body = json.load(response)
    if body.get("version") != 1:
        raise ValueError("unsupported entitlement key version")
    return EntitlementVerifier.from_b64(str(body["key"]))


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
        fetch: Callable[[str], EntitlementVerifier] = fetch_key,
        now: Callable[[], datetime] = utcnow,
        refresh_s: float = REFRESH_S,
        retry_s: float = RETRY_S,
    ) -> None:
        self._url = accounts_url
        self._fetch = fetch
        self._now = now
        self._refresh_s = refresh_s
        self._retry_s = retry_s
        self._verifier: EntitlementVerifier | None = None
        self._recheck = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self.counts: Counter[str] = Counter()

    @property
    def ready(self) -> bool:
        """Whether the accounts key is known, so a certificate can be judged."""
        return self._verifier is not None

    def start(self) -> None:
        self._task = asyncio.create_task(self._keep_key())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _keep_key(self) -> None:
        while True:
            try:
                self._verifier = await asyncio.to_thread(self._fetch, self._url)
                wait = self._refresh_s
            except Exception as error:
                log.warning("relay.entitlement_key_unavailable", error=str(error))
                wait = self._retry_s
            self._recheck.clear()
            with suppress(TimeoutError):
                # A certificate nobody can verify is a sign the key rotated: read it sooner.
                await asyncio.wait_for(self._recheck.wait(), wait)
                await asyncio.sleep(self._retry_s)

    def check(self, opening: RelayOpen) -> tuple[Outcome, EntitlementClaims | None]:
        outcome, claims = self._classify(opening)
        self.counts[outcome.value] += 1
        return outcome, claims

    def _classify(self, opening: RelayOpen) -> tuple[Outcome, EntitlementClaims | None]:
        if opening.entitlement is None:
            return Outcome.NONE, None
        if self._verifier is None:
            return Outcome.UNVERIFIED, None
        try:
            claims = self._verifier.verify(opening.entitlement, now=self._now())
        except InvalidEntitlement as error:
            if error.reason == "forged":
                self._recheck.set()
            return Outcome(error.reason), None
        if claims.key != opening.public_key:
            return Outcome.OTHER_KEY, claims
        return Outcome.VALID, claims
