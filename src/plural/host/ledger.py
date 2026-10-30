from pathlib import Path

from plural.host.writes import WriteTracker
from plural.protocol.events import Event


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
        self._writes = WriteTracker(workspace)
        self._changes: dict[str, tuple[int, int]] = {}

    def observe(self, event: Event) -> None:
        done = self._writes.observe(event)
        if done is None:
            return
        added, removed = diff_stats(done.diff or "")
        before_added, before_removed = self._changes.get(done.path, (0, 0))
        self._changes[done.path] = (before_added + added, before_removed + removed)

    def files(self) -> tuple[tuple[str, int, int], ...]:
        ranked = sorted(self._changes.items(), key=lambda item: (-sum(item[1]), item[0]))
        return tuple((path, added, removed) for path, (added, removed) in ranked)
