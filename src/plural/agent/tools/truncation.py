from typing import Final

MAX_BYTES: Final = 50_000
MAX_LINES: Final = 2000


def truncate_head(text: str, *, max_lines: int = MAX_LINES, max_bytes: int = MAX_BYTES) -> str:
    lines = text.splitlines()
    kept = _fit(lines[:max_lines], max_bytes)
    dropped = len(lines) - len(kept)
    return "\n".join(kept) + (f"\n[truncated {dropped} lines]" if dropped else "")


def truncate_tail(text: str, *, max_lines: int = MAX_LINES, max_bytes: int = MAX_BYTES) -> str:
    lines = text.splitlines()
    kept = list(reversed(_fit(list(reversed(lines[-max_lines:])), max_bytes)))
    dropped = len(lines) - len(kept)
    return (f"[truncated {dropped} lines]\n" if dropped else "") + "\n".join(kept)


def _fit(lines: list[str], max_bytes: int) -> list[str]:
    kept: list[str] = []
    size = 0
    for line in lines:
        size += len(line.encode()) + 1
        if size > max_bytes:
            break
        kept.append(line)
    return kept
