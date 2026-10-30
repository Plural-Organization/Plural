from datetime import UTC, datetime, timedelta
from pathlib import Path

from plural.host.conflicts import ConflictBoard, ago
from plural.host.repo import repo_id_from_remote
from plural.protocol.events import ToolEnded, ToolStarted
from plural.protocol.models import ToolCallView, ToolRisk
from plural.protocol.team import (
    CardDraft,
    Endpoint,
    EndpointKind,
    Peer,
    SessionCard,
    SessionStatus,
    Touch,
)
from plural.relay.presence import conflicts_for, peers_for

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def card(
    owner: str,
    *,
    repo_id: str | None = "github.com/org/api",
    branch: str | None = "main",
    touching: dict[str, timedelta] | None = None,
) -> SessionCard:
    draft = CardDraft(
        room=f"r_{owner}",
        repo="api",
        branch=branch,
        status=SessionStatus.RUNNING,
        endpoints=(Endpoint(kind=EndpointKind.RELAY, url="wss://r.example/r"),),
        repo_id=repo_id,
        touching=tuple(Touch(path=path, at=NOW - age) for path, age in (touching or {}).items()),
    )
    return SessionCard(**draft.model_dump(), owner=owner, owner_id=f"m_{owner}", updated_at=NOW)


MIN = timedelta(minutes=1)


def test_two_people_changing_the_same_file_of_the_same_repository_conflict() -> None:
    alia = card("alia", touching={"src/auth.py": 3 * MIN, "src/a.py": 4 * MIN})
    bek = card("bek", touching={"src/auth.py": 1 * MIN, "src/b.py": 1 * MIN})
    (conflict,) = conflicts_for(alia, [alia, bek], NOW)
    assert (conflict.owner, conflict.room, conflict.paths) == ("bek", "r_bek", ("src/auth.py",))
    assert conflict.same_branch
    assert conflict.latest == NOW - 1 * MIN
    assert conflicts_for(bek, [alia, bek], NOW)[0].owner == "alia"


def test_files_of_the_same_name_in_another_repository_or_with_no_remote_do_not_conflict() -> None:
    alia = card("alia", touching={"src/auth.py": MIN})
    elsewhere = card("bek", repo_id="github.com/org/web", touching={"src/auth.py": MIN})
    assert conflicts_for(alia, [alia, elsewhere], NOW) == ()
    unknown = card("bek", repo_id=None, touching={"src/auth.py": MIN})
    assert conflicts_for(unknown, [alia, unknown], NOW) == ()
    assert conflicts_for(alia, [alia, unknown], NOW) == ()


def test_an_old_change_no_longer_counts() -> None:
    alia = card("alia", touching={"src/auth.py": MIN})
    bek = card("bek", touching={"src/auth.py": 31 * MIN})
    assert conflicts_for(alia, [alia, bek], NOW) == ()
    assert conflicts_for(bek, [alia, bek], NOW) == ()


def test_other_branches_are_marked_so_the_warning_can_say_so() -> None:
    alia = card("alia", branch="main", touching={"src/auth.py": MIN})
    bek = card("bek", branch="feat/x", touching={"src/auth.py": MIN})
    (conflict,) = conflicts_for(alia, [alia, bek], NOW)
    assert not conflict.same_branch
    assert conflict.branch == "feat/x"


def test_nobody_conflicts_with_themselves_and_many_files_are_capped() -> None:
    files = {f"src/f{index}.py": MIN for index in range(30)}
    alia = card("alia", touching=files)
    again = card("alia", touching=files)
    assert conflicts_for(alia, [alia, again], NOW) == ()
    bek = card("bek", touching=files)
    (conflict,) = conflicts_for(alia, [alia, bek], NOW)
    assert len(conflict.paths) == 10


def test_a_host_is_told_what_the_others_in_its_repository_changed_even_if_it_has_not_yet() -> None:
    alia = card("alia")
    bek = card("bek", branch="feat/x", touching={"src/auth.py": 2 * MIN, "src/old.py": 40 * MIN})
    cleo = card("cleo", repo_id="github.com/org/web", touching={"src/auth.py": MIN})
    idle = card("dana")
    (peer,) = peers_for(alia, [alia, bek, cleo, idle], NOW)
    assert (peer.owner, peer.branch, peer.same_branch) == ("bek", "feat/x", False)
    assert [touch.path for touch in peer.touched] == ["src/auth.py"]
    assert peers_for(card("alia", repo_id=None), [bek], NOW) == ()


def test_a_remote_is_reduced_to_host_and_path_without_credentials() -> None:
    expected = "github.com/org/api"
    for remote in [
        "git@github.com:Org/API.git",
        "https://github.com/Org/API.git",
        "https://user:secret@GitHub.com/org/api",
        "ssh://git@github.com/org/api.git",
    ]:
        assert repo_id_from_remote(remote) == expected
    assert repo_id_from_remote("/srv/git/api") is None
    assert repo_id_from_remote("") is None
    assert "secret" not in (repo_id_from_remote("https://user:secret@github.com/org/api") or "")


def started(call_id: str, name: str, subject: str) -> ToolStarted:
    call = ToolCallView(id=call_id, name=name, risk=ToolRisk.WRITE, subject=subject, args={})
    return ToolStarted(run_id="r_1", call=call)


def ended(call_id: str, ok: bool = True) -> ToolEnded:
    return ToolEnded(run_id="r_1", call_id=call_id, ok=ok, output="")


def test_a_finished_edit_is_remembered_relative_to_the_repository(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    board = ConflictBoard(tmp_path)
    board.use_prefix("services/api/")
    board.observe(started("c1", "edit", "src/auth.py"), NOW)
    board.observe(ended("c1"), NOW)
    board.observe(started("c2", "write", str(tmp_path / "src" / "new.py")), NOW)
    board.observe(ended("c2"), NOW)
    paths = {touch.path for touch in board.touching(NOW)}
    assert paths == {"services/api/src/auth.py", "services/api/src/new.py"}


def test_a_failed_edit_a_read_and_a_file_outside_the_workspace_are_not_touches(
    tmp_path: Path,
) -> None:
    board = ConflictBoard(tmp_path)
    board.observe(started("c1", "edit", "a.py"), NOW)
    board.observe(ended("c1", ok=False), NOW)
    board.observe(started("c2", "read", "b.py"), NOW)
    board.observe(ended("c2"), NOW)
    board.observe(started("c3", "edit", "../outside.py"), NOW)
    board.observe(ended("c3"), NOW)
    assert board.touching(NOW) == ()


def test_a_secret_file_is_never_published_as_a_touch(tmp_path: Path) -> None:
    board = ConflictBoard(tmp_path)
    board.observe(started("c1", "write", ".env"), NOW)
    board.observe(ended("c1"), NOW)
    assert board.touching(NOW) == ()


def test_a_touch_is_forgotten_after_half_an_hour_and_the_newest_come_first(
    tmp_path: Path,
) -> None:
    board = ConflictBoard(tmp_path)
    for index, minutes in enumerate([40, 5, 1]):
        board.observe(
            started(f"c{index}", "edit", f"f{index}.py"), NOW - timedelta(minutes=minutes)
        )
        board.observe(ended(f"c{index}"), NOW - timedelta(minutes=minutes))
    assert [touch.path for touch in board.touching(NOW)] == ["f2.py", "f1.py"]


def peer_with(owner: str, path: str, *, same_branch: bool, minutes: int) -> Peer:
    return Peer(
        owner=owner,
        room="r_x",
        branch="main" if same_branch else "feat/x",
        same_branch=same_branch,
        touched=(Touch(path=path, at=NOW - timedelta(minutes=minutes)),),
    )


def test_only_edits_of_a_file_someone_else_changed_get_a_warning(tmp_path: Path) -> None:
    board = ConflictBoard(tmp_path)
    board.update(
        (
            peer_with("alia", "src/auth.py", same_branch=True, minutes=3),
            peer_with("bek", "src/auth.py", same_branch=False, minutes=12),
        )
    )

    def call(name: str, subject: str) -> ToolCallView:
        return ToolCallView(id="c", name=name, risk=ToolRisk.WRITE, subject=subject, args={})

    assert board.warnings_for(call("edit", "src/auth.py"), NOW) == (
        "src/auth.py was also changed by alia 3 min ago",
        "src/auth.py was also changed by bek 12 min ago on feat/x",
    )
    assert board.warnings_for(call("edit", "src/other.py"), NOW) == ()
    assert board.warnings_for(call("bash", "rm src/auth.py"), NOW) == ()
    assert board.warnings_for(call("read", "src/auth.py"), NOW) == ()


def test_times_are_said_in_minutes_and_hours() -> None:
    assert ago(20) == "moments"
    assert ago(5 * 60) == "5 min"
    assert ago(2 * 3600 + 10) == "2 h"
