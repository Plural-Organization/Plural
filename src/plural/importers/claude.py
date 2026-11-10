import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, cast

from plural.importers.model import Candidate, ImportedSession, Turn

TITLE_CHARS: Final = 80
RESULT_CHARS: Final = 400
INPUT_CHARS: Final = 160
REMINDER: Final = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
SYNTHETIC: Final = ("<command-", "<local-command-", "Caveat: The messages below")


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def project_folder(folder: Path) -> str:
    """Claude Code names a project's folder after its path, every other character a dash."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(folder))


def _one_line(text: str, limit: int) -> str:
    line = " ".join(text.split())
    return line if len(line) <= limit else f"{line[: limit - 1]}…"


def _records(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict):
                    out.append(cast(Block, record))
    except OSError:
        return []
    return out


Block = dict[str, Any]


def _blocks(content: object) -> list[Block]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if not isinstance(content, list):
        return []
    return [cast(Block, block) for block in cast(list[object], content) if isinstance(block, dict)]


def _text_of(content: object) -> str:
    return "\n".join(
        str(block["text"])
        for block in _blocks(content)
        if block.get("type") == "text" and "text" in block
    )


def _prompt(text: str) -> str | None:
    text = REMINDER.sub("", text).strip()
    if not text or text.startswith(SYNTHETIC):
        return None
    return text


def _call_note(block: Block) -> str:
    arguments = json.dumps(block.get("input", {}), ensure_ascii=False)
    return f"[called {block.get('name', 'a tool')}: {_one_line(arguments, INPUT_CHARS)}]"


def _result_note(block: Block) -> str:
    text = _text_of(block.get("content")) or str(block.get("content") or "")
    return f"[result: {_one_line(text, RESULT_CHARS)}]"


def turns_of(records: list[dict[str, Any]]) -> list[Turn]:
    turns: list[Turn] = []
    for record in records:
        kind = record.get("type")
        if kind not in ("user", "assistant") or record.get("isSidechain") or record.get("isMeta"):
            continue
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        content: object = cast(Block, message).get("content")
        if kind == "user":
            for block in _blocks(content):
                if block.get("type") == "tool_result":
                    turns.append(Turn(role="tool", text=_result_note(block)))
            text = _prompt(_text_of(content))
            if text is not None:
                turns.append(Turn(role="user", text=text))
            continue
        for block in _blocks(content):
            if block.get("type") == "text" and str(block.get("text", "")).strip():
                turns.append(Turn(role="assistant", text=str(block["text"]).strip()))
            elif block.get("type") == "tool_use":
                turns.append(Turn(role="tool", text=_call_note(block)))
    return turns


def _title(records: list[dict[str, Any]], turns: list[Turn]) -> str:
    for record in reversed(records):
        if record.get("type") == "ai-title" and record.get("aiTitle"):
            return _one_line(str(record["aiTitle"]), TITLE_CHARS)
    first = next((turn.text for turn in turns if turn.role == "user"), "")
    return _one_line(first, TITLE_CHARS) or "untitled"


def _first(records: list[dict[str, Any]], key: str) -> str | None:
    value = next((r[key] for r in records if isinstance(r.get(key), str) and r[key]), None)
    return value if isinstance(value, str) else None


def read(path: Path) -> ImportedSession | None:
    records = _records(path)
    turns = turns_of(records)
    if not turns:
        return None
    return ImportedSession(
        source="claude",
        id=path.stem,
        title=_title(records, turns),
        cwd=_first(records, "cwd"),
        branch=_first(records, "gitBranch"),
        turns=tuple(turns),
    )


def find(folder: Path, *, home: Path | None = None) -> list[Candidate]:
    """The sessions Claude Code kept for this folder, the newest first."""
    root = (home or claude_home()) / "projects" / project_folder(folder.resolve())
    found: list[Candidate] = []
    for path in root.glob("*.jsonl") if root.is_dir() else ():
        session = read(path)
        if session is None:
            continue
        found.append(
            Candidate(
                source="claude",
                id=session.id,
                path=path,
                title=session.title,
                cwd=session.cwd,
                updated_at=datetime.fromtimestamp(path.stat().st_mtime, UTC),
                turns=len(session.turns),
            )
        )
    return sorted(found, key=lambda entry: entry.updated_at, reverse=True)
