import re
from collections.abc import Iterable, Mapping
from fnmatch import fnmatchcase
from pathlib import PurePath
from typing import Final

from pydantic import BaseModel

DENIED_PATH_PATTERNS: Final = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "id_rsa*",
    "id_ecdsa*",
    "id_ed25519*",
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".git/config",
    "*/.git/config",
)
DENIED_DIRECTORIES: Final = frozenset({".ssh", ".aws", ".gnupg", ".plural"})
SECRET_ENV_NAME: Final = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", re.IGNORECASE)
SECRET_VALUE: Final = re.compile(
    r"sk-ant-[A-Za-z0-9_\-]{16,}"
    r"|sk-[A-Za-z0-9_\-]{20,}"
    r"|gh[pousr]_[A-Za-z0-9]{30,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|xox[abprs]-[A-Za-z0-9\-]{10,}"
    r"|AIza[0-9A-Za-z_\-]{35}"
)
MASK: Final = "[REDACTED]"
MIN_SECRET_LENGTH: Final = 8


def is_denied_path(path: PurePath) -> bool:
    if DENIED_DIRECTORIES.intersection(path.parts):
        return True
    posix = path.as_posix()
    return any(fnmatchcase(posix, p) or fnmatchcase(path.name, p) for p in DENIED_PATH_PATTERNS)


class Redactor:
    def __init__(self, values: Iterable[str] = ()) -> None:
        self._values = sorted(
            {v for v in values if len(v) >= MIN_SECRET_LENGTH}, key=len, reverse=True
        )

    def add(self, value: str) -> None:
        if len(value) >= MIN_SECRET_LENGTH and value not in self._values:
            self._values = sorted([*self._values, value], key=len, reverse=True)

    @classmethod
    def from_environment(cls, environ: Mapping[str, str], extra: Iterable[str] = ()) -> "Redactor":
        found = [value for name, value in environ.items() if SECRET_ENV_NAME.search(name)]
        return cls([*found, *extra])

    def redact(self, text: str) -> str:
        for value in self._values:
            text = text.replace(value, MASK)
        return SECRET_VALUE.sub(MASK, text)

    def scrub[M: BaseModel](self, model: M) -> M:
        raw = model.model_dump_json()
        clean = self.redact(raw)
        return model if clean == raw else model.model_validate_json(clean)
