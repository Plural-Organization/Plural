import asyncio
import time
from collections.abc import Callable
from contextlib import suppress

import structlog
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus, WebSocketException

from plural.host.bootstrap import Host
from plural.host.config import HostSettings
from plural.host.repo import RepoFacts, repo_facts
from plural.host.team import DirectoryClient, TeamError, TeamStore
from plural.protocol.models import Role, SessionState
from plural.protocol.team import (
    CardDraft,
    Endpoint,
    EndpointKind,
    PresenceCard,
    SessionStatus,
)
from plural.security.identity import authorization

log = structlog.get_logger(__name__)

HEARTBEAT_S = 20.0
POLL_S = 2.0
REPO_REFRESH_S = 30.0
RETRY_MIN_S = 2.0
RETRY_MAX_S = 60.0
CLOSE_DENIED = 4401


class PresenceUnavailable(Exception):
    pass


def endpoints_of(settings: HostSettings, room: str) -> tuple[Endpoint, ...]:
    kind = EndpointKind.DIRECT if settings.public_url else EndpointKind.RELAY
    return (Endpoint(kind=kind, url=settings.room_url(room)),)


def ensure_ready(settings: HostSettings, store: TeamStore) -> None:
    if store.load() is None:
        raise PresenceUnavailable("you are not in a team: plural team create or plural team join")
    if not (settings.public_url or settings.relay_url):
        raise PresenceUnavailable(
            "a team session must be reachable: start it with --relay, --public-url or a tunnel"
        )


def status_of(state: SessionState) -> SessionStatus:
    if state.approvals or state.proposals or state.join_requests or state.access_requests:
        return SessionStatus.WAITING
    return SessionStatus.RUNNING if state.run is not None else SessionStatus.IDLE


def viewers_of(state: SessionState) -> int:
    return sum(
        1
        for participant in state.participants.values()
        if participant.connected and participant.role is Role.VIEWER
    )


def draft_of(settings: HostSettings, room: str, state: SessionState, repo: RepoFacts) -> CardDraft:
    return CardDraft(
        room=room,
        repo=repo.name,
        branch=repo.branch,
        title=settings.title,
        status=status_of(state),
        viewers=viewers_of(state),
        endpoints=endpoints_of(settings, room),
    )


def presence_url(relay: str, team_id: str) -> str:
    base = relay.strip().rstrip("/")
    scheme = {"http": "ws", "https": "wss"}.get(base.split("://", 1)[0])
    if scheme is not None:
        base = f"{scheme}://{base.split('://', 1)[1]}"
    return f"{base}/teams/{team_id}/presence"


class TeamPresence:
    def __init__(
        self,
        host: Host,
        settings: HostSettings,
        store: TeamStore,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._host = host
        self._settings = settings
        self._store = store
        self._clock = clock
        self._repo = RepoFacts(name=settings.workspace.name or "project", branch=None)
        self._repo_at = float("-inf")

    async def run(self) -> None:
        delay = RETRY_MIN_S
        while True:
            started = self._clock()
            try:
                await self._session()
            except TeamError as error:
                log.warning("team.presence_unavailable", reason=str(error))
            except InvalidStatus as error:
                if error.response.status_code in {401, 403}:
                    log.error("team.presence_stopped", reason="the team refused this host")
                    return
                log.warning("team.presence_refused", status=error.response.status_code)
            except (OSError, WebSocketException) as error:
                log.warning("team.presence_lost", reason=str(error))
            except PresenceUnavailable as error:
                log.error("team.presence_stopped", reason=str(error))
                return
            if self._clock() - started > 3 * HEARTBEAT_S:
                delay = RETRY_MIN_S
            await asyncio.sleep(delay)
            delay = min(RETRY_MAX_S, delay * 2)

    async def _session(self) -> None:
        stored = self._store.load()
        if stored is None:
            raise PresenceUnavailable("you left the team")
        client = DirectoryClient(self._store, stored)
        profile = await client.refresh()
        url = presence_url(profile.relay, profile.team_id)
        path = "/" + url.split("://", 1)[1].split("/", 1)[1]
        header = authorization(
            self._store.identity(),
            profile.certificate,
            "GET",
            path,
            b"",
            timestamp=int(time.time()),
            nonce=time.time_ns().to_bytes(8, "big").hex(),
        )
        async with connect(url, additional_headers={"authorization": header}) as socket:
            log.info("team.presence_connected", team=profile.team_name)
            last: str | None = None
            sent_at = float("-inf")
            while True:
                card = await self._card()
                text = PresenceCard(card=card).model_dump_json()
                if text != last or self._clock() - sent_at >= HEARTBEAT_S:
                    await socket.send(text)
                    last, sent_at = text, self._clock()
                with suppress(TimeoutError):
                    async with asyncio.timeout(POLL_S):
                        await socket.wait_closed()
                if socket.close_code is not None:
                    if socket.close_code == CLOSE_DENIED:
                        raise PresenceUnavailable(
                            socket.close_reason or "the team refused this session"
                        )
                    raise ConnectionError(
                        socket.close_reason or "the directory closed the connection"
                    )

    async def _card(self) -> CardDraft:
        if self._clock() - self._repo_at >= REPO_REFRESH_S:
            self._repo = await repo_facts(self._settings.workspace)
            self._repo_at = self._clock()
        return draft_of(self._settings, self._host.room, self._host.actor.state, self._repo)
