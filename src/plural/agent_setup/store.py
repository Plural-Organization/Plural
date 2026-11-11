"""What this computer remembers about the agent: the choice per provider and the API keys.

The files are the ones the terminal client has always written (`credentials.json` and the `agent`
and `agentChoices` fields of `tui.json`), so a key or choice saved before is found. A write keeps
every field this module does not own.
"""

import json
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Final, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.alias_generators import to_camel

CREDENTIALS: Final = "credentials.json"
SETTINGS: Final = "tui.json"
DEFAULT_PRESET: Final = "demo"
MAX_KEY_CHARS: Final = 4096
_PRESET_ID: Final = re.compile(r"^[a-z0-9_]{1,64}$")


class AgentSetupError(Exception):
    pass


class Choice(BaseModel):
    """A provider with the model, endpoint and window a person picked for it."""

    model_config = ConfigDict(
        frozen=True, alias_generator=to_camel, populate_by_name=True, extra="ignore"
    )

    preset: str = Field(pattern=_PRESET_ID.pattern)
    model: str = Field(default="", max_length=200)
    base_url: str = Field(default="", max_length=2000)
    context_window: str = Field(default="", max_length=12)
    fast_model: str = Field(default="", max_length=200)

    def stored(self) -> dict[str, str]:
        data = self.model_dump(by_alias=True)
        if not self.fast_model:
            del data["fastModel"]
        return data


def _read(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return cast(dict[str, Any], raw) if isinstance(raw, dict) else {}


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temporary = file.name
            os.fchmod(file.fileno(), 0o600)
            file.write(json.dumps(data, indent=2))
            file.write("\n")
        os.replace(temporary, path)
        temporary = None
    except OSError as error:
        raise AgentSetupError(f"could not save {path.name}: {error.strerror or error}") from error
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def _choice(raw: Any) -> Choice | None:
    try:
        return Choice.model_validate(raw)
    except ValidationError:
        return None


def check_preset(preset: str) -> str:
    if not _PRESET_ID.match(preset):
        raise AgentSetupError("not a provider id")
    return preset


class AgentStore:
    def __init__(self, directory: Path) -> None:
        self._credentials = directory / CREDENTIALS
        self._settings = directory / SETTINGS

    def keys(self) -> dict[str, str]:
        stored: object = _read(self._credentials).get("keys")
        if not isinstance(stored, dict):
            return {}
        return {
            name: value
            for name, value in cast(dict[object, object], stored).items()
            if isinstance(name, str) and isinstance(value, str) and value
        }

    def key(self, preset: str) -> str | None:
        return self.keys().get(preset)

    def set_key(self, preset: str, key: str) -> None:
        key = key.strip()
        check_preset(preset)
        if not key or len(key) > MAX_KEY_CHARS or any(char.isspace() for char in key):
            raise AgentSetupError("that does not look like an API key")
        data = _read(self._credentials)
        data["keys"] = {**self.keys(), preset: key}
        _write(self._credentials, data)

    def clear_key(self, preset: str) -> None:
        check_preset(preset)
        data = _read(self._credentials)
        data["keys"] = {name: value for name, value in self.keys().items() if name != preset}
        _write(self._credentials, data)

    def current(self) -> Choice:
        return _choice(_read(self._settings).get("agent")) or Choice(preset=DEFAULT_PRESET)

    def saved(self, preset: str) -> Choice | None:
        choices = _read(self._settings).get("agentChoices")
        if not isinstance(choices, dict):
            return None
        found = _choice(cast(dict[str, Any], choices).get(preset))
        return found.model_copy(update={"preset": preset}) if found else None

    def choose(self, choice: Choice) -> None:
        """Make it the agent, and remember it as what this provider was last set to."""
        data = _read(self._settings)
        choices = data.get("agentChoices")
        data["agent"] = choice.stored()
        data["agentChoices"] = {
            **(choices if isinstance(choices, dict) else {}),
            choice.preset: choice.stored(),
        }
        _write(self._settings, data)
