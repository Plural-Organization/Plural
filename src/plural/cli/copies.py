"""Finds more than one copy of a Plural program on the PATH, so `plural doctor` can say so.

An older copy that comes first runs instead of the one just installed. Installing in a new place
(a package manager, `PLURAL_INSTALL_DIR`, an old `uv tool` install) is how that happens.
"""

import os
from pathlib import Path


def copies_of(name: str, path: str | None = None) -> list[Path]:
    """Every program called `name` on the PATH, in the order a shell finds them, each once."""
    found: list[Path] = []
    for folder in (os.environ.get("PATH", "") if path is None else path).split(os.pathsep):
        if not folder:
            continue
        candidate = Path(folder) / name
        if not (candidate.is_file() and os.access(candidate, os.X_OK)):
            continue
        real = candidate.resolve()
        if real not in found:
            found.append(real)
    return found
