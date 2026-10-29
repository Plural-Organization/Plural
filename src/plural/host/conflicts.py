from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath

from plural.protocol.events import Event, ToolEnded, ToolStarted
from plural.protocol.models import ToolCallView
from plural.protocol.team import Peer, Touch

WRITING_TOOLS = frozenset({"edit", "write"})
WINDOW = timedelta(minutes=30)
LIMIT = 50


def ago(seconds: float) -> str:
    minutes = int(seconds // 60)
    if minutes < 1:
        return "moments"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h"


def warning(path: str, peer: Peer, changed: datetime, now: datetime) -> str:
    since = ago((now - changed).total_seconds())
    where = "" if peer.same_branch else f" on {peer.branch or 'another branch'}"
    return f"{path} was also changed by {peer.owner} {since} ago{where}"


class ConflictBoard:
    def __init__(self, workspace: Path) -> None:
        self._root = workspace.resolve()
        self._prefix = ""
        self._touched: dict[str, datetime] = {}
        self._started: dict[str, ToolCallView] = {}
        self._peers: tuple[Peer, ...] = ()

    @property
    def peers(self) -> tuple[Peer, ...]:
        return self._peers

    def use_prefix(self, prefix: str) -> None:
        self._prefix = prefix

    def update(self, peers: tuple[Peer, ...]) -> None:
        self._peers = peers

    def relative(self, subject: str) -> str | None:
        path = Path(subject)
        resolved = (path if path.is_absolute() else self._root / path).resolve()
        try:
            inside = resolved.relative_to(self._root)
        except ValueError:
            return None
        return str(PurePosixPath(self._prefix) / PurePosixPath(*inside.parts))

    def observe(self, event: Event, now: datetime) -> None:
        if isinstance(event, ToolStarted) and event.call.name in WRITING_TOOLS:
            self._started[event.call.id] = event.call
        elif isinstance(event, ToolEnded):
            call = self._started.pop(event.call_id, None)
            if call is not None and event.ok:
                path = self.relative(call.subject)
                if path is not None:
                    self._touched[path] = now

    def touching(self, now: datetime) -> tuple[Touch, ...]:
        self._touched = {path: at for path, at in self._touched.items() if now - at <= WINDOW}
        recent = sorted(self._touched.items(), key=lambda item: item[1], reverse=True)[:LIMIT]
        return tuple(Touch(path=path, at=at) for path, at in recent)

    def warnings_for(self, call: ToolCallView, now: datetime) -> tuple[str, ...]:
        if call.name not in WRITING_TOOLS:
            return ()
        path = self.relative(call.subject)
        if path is None:
            return ()
        return tuple(
            warning(path, peer, touch.at, now)
            for peer in self._peers
            for touch in peer.touched
            if touch.path == path
        )
