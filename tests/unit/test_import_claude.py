import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from plural.importers import claude
from plural.importers.render import BUDGET, render
from plural.protocol.commands import MAX_BRIEFING_CHARS


def write(path: Path, records: Sequence[Mapping[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\nnot json\n", encoding="utf-8")
    return path


def user(text: object) -> dict[str, object]:
    return {"type": "user", "cwd": "/work/app", "gitBranch": "main", "message": {"content": text}}


def assistant(*blocks: dict[str, object]) -> dict[str, object]:
    return {"type": "assistant", "message": {"content": list(blocks)}}


SESSION: list[Mapping[str, object]] = [
    {"type": "mode", "mode": "normal"},
    user("fix the login bug"),
    assistant(
        {"type": "thinking", "thinking": "", "signature": "x"},
        {"type": "text", "text": "Looking at auth.py"},
        {"type": "tool_use", "name": "Read", "input": {"file_path": "auth.py"}},
    ),
    user([{"type": "tool_result", "tool_use_id": "t", "content": "def login(): ..."}]),
    user("<system-reminder>ignore me</system-reminder>"),
    {**user("sidechain"), "isSidechain": True},
    assistant({"type": "text", "text": "Fixed."}),
]


def test_turns_keep_the_talk_and_reduce_tools_to_notes(tmp_path: Path) -> None:
    session = claude.read(write(tmp_path / "abc.jsonl", SESSION))
    assert session is not None
    assert [(t.role, t.text) for t in session.turns] == [
        ("user", "fix the login bug"),
        ("assistant", "Looking at auth.py"),
        ("tool", '[called Read: {"file_path": "auth.py"}]'),
        ("tool", "[result: def login(): ...]"),
        ("assistant", "Fixed."),
    ]
    assert (session.id, session.cwd, session.branch) == ("abc", "/work/app", "main")
    assert session.title == "fix the login bug"


def test_a_file_without_a_conversation_is_not_a_session(tmp_path: Path) -> None:
    assert claude.read(write(tmp_path / "a.jsonl", [{"type": "mode"}])) is None
    assert claude.read(tmp_path / "missing.jsonl") is None


def test_find_looks_in_the_folders_project_newest_first(tmp_path: Path) -> None:
    folder = tmp_path / "my app"
    folder.mkdir()
    project = tmp_path / "home" / "projects" / claude.project_folder(folder.resolve())
    old = write(project / "old.jsonl", SESSION)
    new = write(project / "new.jsonl", [user("second"), assistant({"type": "text", "text": "ok"})])
    # Explicit times: two touches in a row can land on the same mtime.
    os.utime(old, (1_000_000, 1_000_000))
    os.utime(new, (2_000_000, 2_000_000))
    found = claude.find(folder, home=tmp_path / "home")
    assert [c.id for c in found] == ["new", "old"]
    assert claude.find(tmp_path / "elsewhere", home=tmp_path / "home") == []


def test_render_fits_the_briefing_limit_and_keeps_the_newest(tmp_path: Path) -> None:
    records: list[Mapping[str, object]] = [user("start")]
    for number in range(400):
        records.append(assistant({"type": "text", "text": f"step {number} " + "x" * 900}))
    session = claude.read(write(tmp_path / "big.jsonl", records))
    assert session is not None
    text = render(session)
    assert len(text) <= BUDGET <= MAX_BRIEFING_CHARS
    assert "step 399" in text
    assert "step 0 " not in text
    assert "earlier turns left out" in text


def test_render_of_a_short_session_leaves_nothing_out(tmp_path: Path) -> None:
    session = claude.read(write(tmp_path / "s.jsonl", SESSION))
    assert session is not None
    text = render(session)
    assert "fix the login bug" in text
    assert "left out" not in text
    assert "Folder: /work/app" in text
