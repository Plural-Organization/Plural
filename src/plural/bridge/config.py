"""The credentials of each chat service, kept in one private file.

`<data dir>/bridge/config.json`, readable by its owner only. A secret is written here and never
read back out: the catalog says only that one is set.
"""

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from plural.bridge.registry import Provider

MAX_VALUE_CHARS = 4096


class ConfigError(ValueError):
    pass


class Entry(BaseModel):
    enabled: bool = True
    values: dict[str, str] = Field(default_factory=dict[str, str])


class _Saved(BaseModel):
    providers: dict[str, Entry] = Field(default_factory=dict[str, Entry])


class BridgeConfig:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "bridge" / "config.json"
        self._stamp = 0
        self._saved = self._load()

    def reload(self) -> bool:
        """Reads the file again when another process changed it. True when it changed."""
        try:
            stamp = self.path.stat().st_mtime_ns
        except OSError:
            stamp = 0
        if stamp == self._stamp:
            return False
        self._saved = self._load()
        return True

    def get(self, provider_id: str) -> Entry | None:
        entry = self._saved.providers.get(provider_id)
        return None if entry is None else entry.model_copy(deep=True)

    def ids(self) -> list[str]:
        return list(self._saved.providers)

    def save(
        self, provider: Provider, values: dict[str, str], *, enabled: bool | None = None
    ) -> Entry:
        """Adds or changes a provider's values. An empty secret keeps the one saved."""
        known = {item.id: item for item in provider.fields}
        for key in values:
            if key not in known:
                raise ConfigError(f"{provider.label} has no setting called {key}")
        before = self._saved.providers.get(provider.id)
        merged = dict(before.values) if before else {}
        for key, value in values.items():
            text = value.strip()
            if len(text) > MAX_VALUE_CHARS:
                raise ConfigError(f"{known[key].label} is too long")
            if text:
                merged[key] = text
            elif not known[key].secret:
                merged.pop(key, None)
        for item in provider.fields:
            if item.required and not merged.get(item.id):
                raise ConfigError(f"{item.label} is required")
        entry = Entry(
            enabled=before.enabled if before and enabled is None else enabled is not False,
            values=merged,
        )
        self._saved.providers[provider.id] = entry
        self._save()
        return entry.model_copy(deep=True)

    def set_enabled(self, provider_id: str, enabled: bool) -> None:
        entry = self._saved.providers.get(provider_id)
        if entry is None:
            raise ConfigError(f"{provider_id} is not set up")
        entry.enabled = enabled
        self._save()

    def remove(self, provider_id: str) -> bool:
        removed = self._saved.providers.pop(provider_id, None) is not None
        if removed:
            self._save()
        return removed

    def _load(self) -> _Saved:
        try:
            self._stamp = self.path.stat().st_mtime_ns
        except OSError:
            self._stamp = 0
        try:
            return _Saved.model_validate_json(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return _Saved()
        except (OSError, ValidationError, json.JSONDecodeError) as error:
            raise ConfigError(f"{self.path} is unreadable: {error}") from error

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.path.with_suffix(".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(self._saved.model_dump_json(indent=2))
        temporary.replace(self.path)
        self._stamp = self.path.stat().st_mtime_ns
