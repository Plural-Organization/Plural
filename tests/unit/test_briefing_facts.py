from datetime import UTC, datetime
from pathlib import Path

from plural.host.briefing import MAX_FILES, TRUNCATED, assemble, facts_block
from plural.host.ledger import ChangeLedger, diff_stats
from plural.protocol.commands import MAX_BRIEFING_CHARS
from plural.protocol.events import ToolEnded, ToolStarted
from plural.protocol.models import ToolCallView, ToolRisk

WHEN = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
DIFF = "--- a/x\n+++ b/x\n@@\n-old\n+new\n+newer\n context\n"


def started(call_id: str, name: str, subject: str) -> ToolStarted:
    call = ToolCallView(id=call_id, name=name, risk=ToolRisk.WRITE, subject=subject, args={})
    return ToolStarted(run_id="r", call=call)


def ended(call_id: str, *, ok: bool = True, diff: str | None = DIFF) -> ToolEnded:
    return ToolEnded(run_id="r", call_id=call_id, ok=ok, output="", diff=diff)


def test_a_diff_is_counted_without_its_headers() -> None:
    assert diff_stats(DIFF) == (2, 1)
    assert diff_stats("") == (0, 0)


def test_the_ledger_adds_up_what_each_file_went_through(tmp_path: Path) -> None:
    ledger = ChangeLedger(tmp_path)
    for index in range(2):
        ledger.observe(started(f"a{index}", "edit", "src/auth.py"))
        ledger.observe(ended(f"a{index}"))
    ledger.observe(started("b", "write", str(tmp_path / "notes.md")))
    ledger.observe(ended("b", diff="+one\n+two\n+three\n"))
    assert ledger.files() == (("src/auth.py", 4, 2), ("notes.md", 3, 0))


def test_failed_edits_reads_secrets_and_outside_files_are_left_out(tmp_path: Path) -> None:
    ledger = ChangeLedger(tmp_path)
    ledger.observe(started("a", "edit", "a.py"))
    ledger.observe(ended("a", ok=False))
    ledger.observe(started("b", "read", "b.py"))
    ledger.observe(ended("b"))
    ledger.observe(started("c", "write", ".env"))
    ledger.observe(ended("c"))
    ledger.observe(started("d", "edit", "../elsewhere.py"))
    ledger.observe(ended("d"))
    assert ledger.files() == ()


def test_the_facts_name_the_repository_the_branch_the_commit_and_the_files() -> None:
    text = facts_block(
        repo="github.com/org/api",
        branch="feat/x",
        head="abc1234",
        dirty=3,
        files=(("src/auth.py", 34, 8), ("notes.md", 1, 0)),
    )
    assert text.splitlines()[0] == (
        "repository github.com/org/api · branch feat/x · HEAD abc1234"
        " · 3 files with uncommitted changes"
    )
    assert "- src/auth.py  +34 −8" in text
    assert "(from the tool log)" in text


def test_the_facts_cope_with_no_git_and_no_changes_and_cap_a_long_list() -> None:
    bare = facts_block(repo="api", branch=None, head=None, dirty=None, files=())
    assert bare.splitlines() == ["repository api", "No file was changed in this session yet."]
    many = facts_block(
        repo="api",
        branch=None,
        head=None,
        dirty=1,
        files=tuple((f"f{n}.py", 1, 0) for n in range(MAX_FILES + 5)),
    )
    assert "1 file with uncommitted changes" in many
    assert "- and 5 more" in many
    assert f"f{MAX_FILES}.py" not in many


def test_the_briefing_says_whose_it_is_how_fresh_and_whether_it_is_an_update() -> None:
    text = assemble("alia", WHEN, 42, "repository api", "Goal: fix login", update=False)
    assert text.startswith("Briefing from alia's session, as of event 42 (2026-10-29 12:00 UTC).")
    assert text.endswith("Goal: fix login")
    again = assemble("alia", WHEN, 50, "repository api", "nothing new", update=True)
    assert again.startswith("Update to the earlier briefing from alia's session, as of event 50")
    assert "has not done anything" in assemble("alia", WHEN, 1, "f", "  ", update=False)


def test_a_briefing_that_is_too_long_is_cut_and_says_so() -> None:
    text = assemble("alia", WHEN, 1, "facts", "x" * (MAX_BRIEFING_CHARS * 2), update=False)
    assert len(text) == MAX_BRIEFING_CHARS
    assert text.endswith(TRUNCATED)
