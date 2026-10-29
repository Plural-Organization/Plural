import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from plural.protocol.team import CardDraft, Conflict, MemberClaims, Peer, SessionCard


@dataclass(slots=True)
class _Entry:
    card: SessionCard
    seen: float
    holder: object


class Presence:
    def __init__(
        self,
        *,
        ttl_s: float = 60.0,
        max_per_member: int = 5,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_s = ttl_s
        self._max_per_member = max_per_member
        self._clock = clock
        self._entries: dict[tuple[str, str], _Entry] = {}

    def publish(
        self, claims: MemberClaims, draft: CardDraft, holder: object, now: datetime
    ) -> bool:
        key = (claims.team, draft.room)
        existing = self._entries.get(key)
        if existing is not None and existing.card.owner_id != claims.member:
            return False
        if existing is None and self._count(claims) >= self._max_per_member:
            return False
        card = SessionCard(
            **draft.model_dump(), owner=claims.name, owner_id=claims.member, updated_at=now
        )
        self._entries[key] = _Entry(card, self._clock(), holder)
        return True

    def touch(self, team: str, room: str) -> None:
        entry = self._entries.get((team, room))
        if entry is not None:
            entry.seen = self._clock()

    def drop_held_by(self, holder: object) -> None:
        for key in [key for key, entry in self._entries.items() if entry.holder is holder]:
            del self._entries[key]

    def sessions(self, team: str, now: datetime) -> tuple[SessionCard, ...]:
        self._sweep()
        cards = [entry.card for (owner, _), entry in self._entries.items() if owner == team]
        ordered = sorted(cards, key=lambda card: (card.owner.lower(), card.room))
        return tuple(
            card.model_copy(update={"conflicts": conflicts_for(card, ordered, now)})
            for card in ordered
        )

    def peers_of(self, team: str, room: str, now: datetime) -> tuple[Peer, ...]:
        cards = self.sessions(team, now)
        mine = next((card for card in cards if card.room == room), None)
        return () if mine is None else peers_for(mine, cards, now)

    def forget_team(self, team: str) -> None:
        for key in [key for key in self._entries if key[0] == team]:
            del self._entries[key]

    def forget_member(self, team: str, member: str) -> None:
        for key, entry in list(self._entries.items()):
            if key[0] == team and entry.card.owner_id == member:
                del self._entries[key]

    def _count(self, claims: MemberClaims) -> int:
        return sum(
            1
            for (team, _), entry in self._entries.items()
            if team == claims.team and entry.card.owner_id == claims.member
        )

    def _sweep(self) -> None:
        horizon = self._clock() - self._ttl_s
        for key in [key for key, entry in self._entries.items() if entry.seen < horizon]:
            del self._entries[key]


CONFLICT_WINDOW = timedelta(minutes=30)
MAX_CONFLICT_PATHS = 10


def conflicts_for(
    card: SessionCard, others: Iterable[SessionCard], now: datetime
) -> tuple[Conflict, ...]:
    if card.repo_id is None:
        return ()
    mine = {touch.path for touch in card.touching if now - touch.at <= CONFLICT_WINDOW}
    found: list[Conflict] = []
    for other in others:
        if other.owner_id == card.owner_id or other.repo_id != card.repo_id:
            continue
        shared = {
            touch.path: touch.at
            for touch in other.touching
            if touch.path in mine and now - touch.at <= CONFLICT_WINDOW
        }
        if not shared:
            continue
        found.append(
            Conflict(
                owner=other.owner,
                room=other.room,
                branch=other.branch,
                paths=tuple(sorted(shared))[:MAX_CONFLICT_PATHS],
                same_branch=other.branch == card.branch,
                latest=max(shared.values()),
            )
        )
    return tuple(sorted(found, key=lambda conflict: (conflict.owner.lower(), conflict.room)))


def peers_for(card: SessionCard, others: Iterable[SessionCard], now: datetime) -> tuple[Peer, ...]:
    if card.repo_id is None:
        return ()
    found: list[Peer] = []
    for other in others:
        if other.owner_id == card.owner_id or other.repo_id != card.repo_id:
            continue
        touched = tuple(touch for touch in other.touching if now - touch.at <= CONFLICT_WINDOW)
        if touched:
            found.append(
                Peer(
                    owner=other.owner,
                    room=other.room,
                    branch=other.branch,
                    same_branch=other.branch == card.branch,
                    touched=touched,
                )
            )
    return tuple(sorted(found, key=lambda peer: (peer.owner.lower(), peer.room)))
