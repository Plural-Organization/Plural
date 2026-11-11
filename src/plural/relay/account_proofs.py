from collections.abc import Callable
from datetime import datetime, timedelta

from plural.protocol.team import AccountProof, account_proof_message
from plural.relay.directory import DirectoryError
from plural.security.entitlement import EntitlementVerifier, InvalidEntitlement
from plural.security.identity import verify_signature
from plural.security.replay import ReplayGuard

SKEW_S = 60


class AccountProofs:
    """Says which account a team request comes from (ADR 0016), offline, with the accounts key.

    A browser proves its account with a ticket for `teams`; a computer with its entitlement
    certificate and a signature by the certificate's key over a fresh time and nonce. Each proof
    works once.
    """

    def __init__(
        self,
        verifier: Callable[[], EntitlementVerifier | None],
        *,
        suspect: Callable[[], None] = lambda: None,
        skew_s: int = SKEW_S,
    ) -> None:
        self._verifier = verifier
        self._suspect = suspect
        self._skew_s = skew_s
        self._replays = ReplayGuard(timedelta(seconds=2 * skew_s))

    def account_of(self, proof: AccountProof, now: datetime) -> str:
        verifier = self._verifier()
        if verifier is None:
            raise DirectoryError(503, "this relay has not read the accounts key yet, try again")
        try:
            if proof.ticket is not None:
                claims = verifier.ticket(proof.ticket, now=now, audience="teams")
                self._once(f"ticket:{claims.nonce}", now)
                return claims.account
            if proof.certificate and proof.ts is not None and proof.nonce and proof.signature:
                certificate = verifier.verify(proof.certificate, now=now)
                if abs(int(now.timestamp()) - proof.ts) > self._skew_s:
                    raise DirectoryError(401, "your clock is off by more than a minute")
                message = account_proof_message(proof.ts, proof.nonce)
                if not verify_signature(certificate.key, message, proof.signature):
                    raise DirectoryError(401, "the certificate's key did not sign this request")
                self._once(f"certificate:{certificate.key}:{proof.nonce}", now)
                return certificate.account
        except InvalidEntitlement as error:
            if error.reason == "forged":
                # A rotated accounts key looks like a forgery: read it again soon.
                self._suspect()
            raise DirectoryError(401, f"the account proof is {error.reason}") from error
        raise DirectoryError(400, "an account proof is a ticket, or a certificate with a signature")

    def _once(self, key: str, now: datetime) -> None:
        if not self._replays.fresh(key, now):
            raise DirectoryError(401, "that account proof was already used")
