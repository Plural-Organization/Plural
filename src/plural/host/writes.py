from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from plural.protocol.events import Event, ToolEnded, ToolStarted
from plural.protocol.models import ToolCallView
from plural.security.secrets import is_denied_path

WRITING_TOOLS = frozenset({"edit", "write"})


@dataclass(frozen=True, slots=True)
class Write:
    path: str
    diff: str | None


class WriteTracker:
    def __init__(self, workspace: Path) -> None:
        self._root = workspace.resolve()
        self._started: dict[str, ToolCallView] = {}

    def path_of(self, subject: str) -> str | None:
        path = Path(subject)
        resolved = (path if path.is_absolute() else self._root / path).resolve()
        try:
            inside = PurePosixPath(*resolved.relative_to(self._root).parts)
        except ValueError:
            return None
        return None if is_denied_path(inside) else str(inside)

    def observe(self, event: Event) -> Write | None:
        if isinstance(event, ToolStarted) and event.call.name in WRITING_TOOLS:
            self._started[event.call.id] = event.call
        elif isinstance(event, ToolEnded):
            call = self._started.pop(event.call_id, None)
            if call is not None and event.ok:
                path = self.path_of(call.subject)
                if path is not None:
                    return Write(path, event.diff)
        return None
