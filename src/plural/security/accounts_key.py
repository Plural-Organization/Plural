import asyncio
from collections.abc import Callable
from contextlib import suppress

import structlog

from plural.security.entitlement import EntitlementVerifier, fetch_verifier

log = structlog.get_logger(__name__)

REFRESH_S = 3600.0
RETRY_S = 30.0


class AccountsKey:
    """Keeps an accounts service's public key at hand without ever waiting for the network.

    The key is read in the background at start, every hour, and sooner after `suspect()`, which
    a caller uses when something signed with the old key shows up (a rotation). Until the first
    read succeeds `verifier` is None and the caller says it cannot tell.
    """

    def __init__(
        self,
        accounts_url: str,
        *,
        fetch: Callable[[str], EntitlementVerifier] = fetch_verifier,
        refresh_s: float = REFRESH_S,
        retry_s: float = RETRY_S,
    ) -> None:
        self._url = accounts_url
        self._fetch = fetch
        self._refresh_s = refresh_s
        self._retry_s = retry_s
        self.verifier: EntitlementVerifier | None = None
        self._suspect = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def ready(self) -> bool:
        return self.verifier is not None

    def suspect(self) -> None:
        self._suspect.set()

    def start(self) -> None:
        self._task = asyncio.create_task(self._keep())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _keep(self) -> None:
        while True:
            try:
                self.verifier = await asyncio.to_thread(self._fetch, self._url)
                wait = self._refresh_s
            except Exception as error:
                log.warning("accounts.key_unavailable", error=str(error))
                wait = self._retry_s
            self._suspect.clear()
            with suppress(TimeoutError):
                await asyncio.wait_for(self._suspect.wait(), wait)
                # Never read more often than the retry interval, however much looks forged.
                await asyncio.sleep(self._retry_s)
