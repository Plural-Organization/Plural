from pathlib import Path, PurePosixPath

from plural.protocol.events import Event, ToolEnded, ToolStarted
from plural.protocol.models import ToolCallView
from plural.security.secrets import is_denied_path

WRITING_TOOLS = frozenset({"edit", "write"})


def diff_stats(diff: str) -> tuple[int, int]:
    added = removed = 0
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


class ChangeLedger:
    def __init__(self, workspace: Path) -> None:
        self._root = workspace.resolve()
        self._started: dict[str, ToolCallView] = {}
        self._changes: dict[str, tuple[int, int]] = {}

    def observe(self, event: Event) -> None:
        if isinstance(event, ToolStarted) and event.call.name in WRITING_TOOLS:
            self._started[event.call.id] = event.call
        elif isinstance(event, ToolEnded):
            call = self._started.pop(event.call_id, None)
            if call is None or not event.ok:
                return
            path = self._relative(call.subject)
            if path is None:
                return
            added, removed = diff_stats(event.diff or "")
            before_added, before_removed = self._changes.get(path, (0, 0))
            self._changes[path] = (before_added + added, before_removed + removed)

    def files(self) -> tuple[tuple[str, int, int], ...]:
        ranked = sorted(self._changes.items(), key=lambda item: (-sum(item[1]), item[0]))
        return tuple((path, added, removed) for path, (added, removed) in ranked)

    def _relative(self, subject: str) -> str | None:
        path = Path(subject)
        resolved = (path if path.is_absolute() else self._root / path).resolve()
        try:
            inside = resolved.relative_to(self._root)
        except ValueError:
            return None
        if is_denied_path(PurePosixPath(*inside.parts)):
            return None
        return str(PurePosixPath(*inside.parts))
