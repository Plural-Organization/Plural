import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from plural.cli import main
from plural.cli.main import app
from plural.host.bootstrap import remember_session
from plural.host.config import HostSettings
from plural.protocol.events import ParticipantJoined, PromptAccepted
from plural.protocol.models import Delivery, Origin, Participant, Provenance, Role
from plural.storage.sessions import delete_session, list_sessions, read_session, session_path
from plural.storage.sqlite_store import SqliteEventStore

runner = CliRunner()
START = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
HOST = Participant(id="p_host", name="vlad", role=Role.HOST, connected=True)
ALIA = Participant(id="p_alia", name="Alia", role=Role.PARTICIPANT, connected=True)
DIRECT = Provenance(initiator_id="p_host", initiator_role=Role.HOST, origin=Origin.DIRECT)


@pytest.fixture(autouse=True)
def data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("PLURAL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("PLURAL_WORKSPACE", raising=False)
    return tmp_path / "data"


async def make(
    data_dir: Path,
    room: str,
    *,
    when: datetime,
    prompts: tuple[str, ...] = (),
    workspace: Path | None = None,
    title: str | None = None,
) -> None:
    store = await SqliteEventStore.open(session_path(data_dir, room))
    for index, who in enumerate((HOST, ALIA)):
        await store.append(
            ParticipantJoined(participant=who),
            event_id=f"{room}-j{index}",
            ts=when,
            actor_id=who.id,
        )
    for index, text in enumerate(prompts):
        await store.append(
            PromptAccepted(
                prompt_id=f"pm_{index}",
                author_id="p_host",
                text=text,
                delivery=Delivery.NOW,
                provenance=DIRECT,
            ),
            event_id=f"{room}-p{index}",
            ts=when + timedelta(minutes=index + 1),
            actor_id="p_host",
        )
    if workspace is not None:
        settings = HostSettings(workspace=workspace, data_dir=data_dir, title=title)
        await remember_session(store, workspace, settings, when)
    await store.close()


def build(data_dir: Path, room: str, **options: object) -> None:
    asyncio.run(make(data_dir, room, **options))  # type: ignore[arg-type]


def test_a_session_is_listed_with_its_first_prompt_as_the_title(data: Path, tmp_path: Path) -> None:
    folder = tmp_path / "app"
    folder.mkdir()
    build(
        data,
        "r_AAAA1",
        when=START,
        prompts=("\n  fix the login bug\nplease", "second"),
        workspace=folder,
    )
    (info,) = list_sessions(data)
    assert (info.room, info.title, info.workspace) == ("r_AAAA1", "fix the login bug", str(folder))
    assert (info.prompts, info.people) == (2, 2)
    assert info.created_at == START
    assert info.updated_at == START + timedelta(minutes=2)


def test_a_chosen_title_wins_and_a_long_prompt_is_cut(data: Path, tmp_path: Path) -> None:
    build(data, "r_AAAA1", when=START, prompts=("x" * 200,))
    assert list_sessions(data)[0].title == "x" * 79 + "…"
    folder = tmp_path / "app"
    folder.mkdir()
    build(data, "r_BBBB2", when=START, prompts=("hello",), workspace=folder, title="refactor auth")
    assert {info.room: info.title for info in list_sessions(data)}["r_BBBB2"] == "refactor auth"


def test_the_newest_session_comes_first_and_the_folder_filters(data: Path, tmp_path: Path) -> None:
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir()
    two.mkdir()
    build(data, "r_OLD01", when=START, prompts=("a",), workspace=one)
    build(data, "r_NEW02", when=START + timedelta(days=1), prompts=("b",), workspace=two)
    build(data, "r_MID03", when=START + timedelta(hours=5), prompts=("c",), workspace=one)
    assert [info.room for info in list_sessions(data)] == ["r_NEW02", "r_MID03", "r_OLD01"]
    assert [info.room for info in list_sessions(data, workspace=one)] == ["r_MID03", "r_OLD01"]


def test_a_session_without_a_prompt_and_a_broken_file_do_not_break_the_list(data: Path) -> None:
    build(data, "r_EMPTY1", when=START)
    session_path(data, "r_JUNK01").write_bytes(b"not a database")
    (info,) = list_sessions(data)
    assert (info.room, info.title, info.prompts) == ("r_EMPTY1", "(no prompt yet)", 0)
    assert read_session(session_path(data, "r_JUNK01")) is None


def test_no_sessions_folder_is_an_empty_list(data: Path) -> None:
    assert list_sessions(data) == []


@pytest.mark.parametrize("room", ["../x", "r_", "r_a/b", "r_x y", "x_AAAA", "r_" + "a" * 90])
def test_an_id_that_is_not_a_session_id_is_refused(data: Path, room: str) -> None:
    with pytest.raises(ValueError, match="not a session id"):
        session_path(data, room)
    with pytest.raises(ValueError, match="not a session id"):
        delete_session(data, room)


def test_deleting_removes_the_log_and_its_side_files(data: Path) -> None:
    build(data, "r_AAAA1", when=START, prompts=("a",))
    path = session_path(data, "r_AAAA1")
    path.with_name(path.name + "-wal").write_bytes(b"x")
    assert delete_session(data, "r_AAAA1") is True
    assert list(path.parent.iterdir()) == []
    assert delete_session(data, "r_AAAA1") is False


def test_the_sessions_command_gives_json_for_scripts(data: Path, tmp_path: Path) -> None:
    folder = tmp_path / "app"
    folder.mkdir()
    build(data, "r_AAAA1", when=START, prompts=("a",), workspace=folder)
    build(data, "r_BBBB2", when=START + timedelta(hours=1), prompts=("b",))
    result = runner.invoke(app, ["sessions", "--json"])
    assert result.exit_code == 0
    assert [entry["room"] for entry in json.loads(result.output)] == ["r_BBBB2", "r_AAAA1"]
    scoped = runner.invoke(app, ["sessions", "--json", "--workspace", str(folder)])
    assert [entry["room"] for entry in json.loads(scoped.output)] == ["r_AAAA1"]


def test_the_sessions_table_names_the_title_and_the_full_id(data: Path) -> None:
    build(data, "r_01M61965AM97DT4NBFAZJ6V6VT", when=START, prompts=("fix the login bug",))
    result = runner.invoke(app, ["sessions"])
    assert "fix the login bug" in result.output
    assert "r_01M61965AM97DT4NBFAZJ6V6VT" in result.output


def test_rm_asks_unless_told_not_to_and_refuses_a_bad_id(data: Path) -> None:
    build(data, "r_AAAA1", when=START, prompts=("a",))
    assert runner.invoke(app, ["rm", "r_AAAA1"], input="n\n").exit_code == 1
    assert read_session(session_path(data, "r_AAAA1")) is not None
    assert runner.invoke(app, ["rm", "r_AAAA1", "--yes"]).exit_code == 0
    assert read_session(session_path(data, "r_AAAA1")) is None
    assert runner.invoke(app, ["rm", "r_AAAA1", "--yes"]).exit_code == 1
    assert runner.invoke(app, ["rm", "../../etc/passwd", "--yes"]).exit_code == 2


def host_settings(monkeypatch: pytest.MonkeyPatch, arguments: list[str]) -> HostSettings | None:
    seen: list[HostSettings] = []

    async def fake_host(settings: HostSettings, *, machine: bool) -> None:
        seen.append(settings)

    monkeypatch.setattr(main, "_host", fake_host)
    result = runner.invoke(app, ["host", *arguments])
    return seen[0] if result.exit_code == 0 and seen else None


def test_resuming_a_room_goes_back_to_the_folder_it_worked_in(
    data: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "app"
    folder.mkdir()
    build(data, "r_AAAA1", when=START, prompts=("a",), workspace=folder)
    settings = host_settings(monkeypatch, ["--room", "r_AAAA1"])
    assert settings is not None
    assert settings.workspace == folder
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()
    chosen = host_settings(monkeypatch, ["--room", "r_AAAA1", "--workspace", str(elsewhere)])
    assert chosen is not None
    assert chosen.workspace == elsewhere


def test_resuming_says_so_when_the_room_or_its_folder_is_gone(
    data: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "app"
    folder.mkdir()
    build(data, "r_AAAA1", when=START, prompts=("a",), workspace=folder)
    folder.rmdir()
    assert host_settings(monkeypatch, ["--room", "r_AAAA1"]) is None
    result = runner.invoke(app, ["host", "--room", "r_AAAA1"])
    assert "folder of this session is gone" in result.output
    unknown = runner.invoke(app, ["host", "--room", "r_NOPE01"])
    assert unknown.exit_code == 1
    assert "no session r_NOPE01" in unknown.output


def test_a_title_is_stored_with_the_session(data: Path, tmp_path: Path) -> None:
    folder = tmp_path / "app"
    folder.mkdir()
    build(data, "r_AAAA1", when=START, prompts=("hello",), workspace=folder, title="refactor auth")
    assert read_session(session_path(data, "r_AAAA1")) is not None
    info = list_sessions(data)[0]
    assert (info.title, info.host_name) == ("refactor auth", "host")
