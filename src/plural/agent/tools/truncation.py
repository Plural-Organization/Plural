from collections import OrderedDict
from typing import Final

MAX_BYTES: Final = 50_000
MAX_LINES: Final = 2000
OUTPUT_PREFIX: Final = "output:"
OUTPUTS_KEPT: Final = 20
MAX_KEPT_BYTES: Final = 5_000_000


class FullOutputs:
    """Outputs too long for a tool result, kept for the session so the model can page through
    them with read instead of running the command again."""

    def __init__(self) -> None:
        self._kept: OrderedDict[str, str] = OrderedDict()
        self._count = 0

    def keep(self, text: str) -> str:
        self._count += 1
        ref = f"{OUTPUT_PREFIX}{self._count}"
        self._kept[ref] = text.encode()[-MAX_KEPT_BYTES:].decode(errors="ignore")
        while len(self._kept) > OUTPUTS_KEPT:
            self._kept.popitem(last=False)
        return ref

    def get(self, ref: str) -> str | None:
        return self._kept.get(ref)


def truncate_head(text: str, *, max_lines: int = MAX_LINES, max_bytes: int = MAX_BYTES) -> str:
    lines = text.splitlines()
    kept = _fit(lines[:max_lines], max_bytes)
    dropped = len(lines) - len(kept)
    return "\n".join(kept) + (f"\n[truncated {dropped} lines]" if dropped else "")


def truncate_tail(
    text: str,
    *,
    max_lines: int = MAX_LINES,
    max_bytes: int = MAX_BYTES,
    full: FullOutputs | None = None,
) -> str:
    lines = text.splitlines()
    kept = list(reversed(_fit(list(reversed(lines[-max_lines:])), max_bytes)))
    dropped = len(lines) - len(kept)
    if not dropped:
        return "\n".join(kept)
    where = (
        f"; the whole output is {full.keep(text)}, read it with offset and limit"
        if full is not None
        else ""
    )
    return f"[truncated {dropped} lines{where}]\n" + "\n".join(kept)


def _fit(lines: list[str], max_bytes: int) -> list[str]:
    kept: list[str] = []
    size = 0
    for line in lines:
        size += len(line.encode()) + 1
        if size > max_bytes:
            break
        kept.append(line)
    return kept
