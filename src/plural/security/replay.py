from datetime import datetime, timedelta


class ReplayGuard:
    def __init__(self, window: timedelta) -> None:
        self._window = window
        self._seen: dict[str, datetime] = {}

    def fresh(self, key: str, now: datetime) -> bool:
        horizon = now - self._window
        for stale in [key for key, at in self._seen.items() if at < horizon]:
            del self._seen[stale]
        if key in self._seen:
            return False
        self._seen[key] = now
        return True
