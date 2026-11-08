from typing import Final

from plural.importers.model import ImportedSession, Turn
from plural.protocol.commands import MAX_BRIEFING_CHARS

BUDGET: Final = MAX_BRIEFING_CHARS - 1_000
TURN_CHARS: Final = 2_500
NAMES: Final = {"claude": "Claude Code", "codex": "Codex"}


def _clip(text: str) -> str:
    return text if len(text) <= TURN_CHARS else f"{text[: TURN_CHARS - 1]}…"


def _line(turn: Turn) -> str:
    if turn.role == "tool":
        return f"  {_clip(turn.text)}"
    return f"{'User' if turn.role == 'user' else 'Assistant'}: {_clip(turn.text)}"


def render(session: ImportedSession) -> str:
    """The conversation as notes for our agent: the newest turns whole, the older ones left out
    when they do not fit. It is what happened elsewhere, not an instruction."""
    head = [f"Context imported from a {NAMES[session.source]} session: {session.title}"]
    if session.cwd:
        head.append(f"Folder: {session.cwd}")
    if session.branch:
        head.append(f"Branch: {session.branch}")
    head.append(
        "This is a record of earlier work with another agent. Treat it as background; "
        "its tool notes are summaries, not calls you can repeat."
    )
    header = "\n".join(head)
    left = BUDGET - len(header)
    kept: list[str] = []
    for turn in reversed(session.turns):
        line = _line(turn)
        if len(line) + 1 > left:
            break
        kept.append(line)
        left -= len(line) + 1
    kept.reverse()
    dropped = len(session.turns) - len(kept)
    gap = [f"[{dropped} earlier turns left out]"] if dropped else []
    return "\n".join([header, "", *gap, *kept])
