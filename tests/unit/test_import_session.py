import json
import os
from pathlib import Path

import pytest

from plural.host.bootstrap import build_host
from plural.host.config import HostSettings
from plural.host.providers import ConfigError
from plural.importers import ImportNotFound, bring_in
from plural.importers.claude import project_folder
from plural.protocol.events import BriefingImported


def keep(home: Path, folder: Path, name: str, prompt: str) -> None:
    project = home / "projects" / project_folder(folder.resolve())
    project.mkdir(parents=True, exist_ok=True)
    records = [
        {"type": "user", "cwd": str(folder), "message": {"content": prompt}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}},
    ]
    (project / f"{name}.jsonl").write_text("\n".join(json.dumps(r) for r in records))


def test_the_newest_session_is_brought_in_by_default(tmp_path: Path) -> None:
    folder = tmp_path / "app"
    folder.mkdir()
    keep(tmp_path / "home", folder, "aaaa1111", "first task")
    keep(tmp_path / "home", folder, "bbbb2222", "second task")
    project = tmp_path / "home/projects" / project_folder(folder.resolve())
    os.utime(project / "bbbb2222.jsonl", (1_000, 1_000))
    os.utime(project / "aaaa1111.jsonl", (2_000, 2_000))
    found = bring_in("claude", folder, home=tmp_path / "home")
    assert found.source == "Claude Code aaaa1111"
    assert found.as_of == 2
    assert "first task" in found.text


def test_an_id_start_picks_one_and_a_wrong_one_says_so(tmp_path: Path) -> None:
    folder = tmp_path / "app"
    folder.mkdir()
    keep(tmp_path / "home", folder, "aaaa1111", "first task")
    keep(tmp_path / "home", folder, "bbbb2222", "second task")
    assert "second task" in bring_in("claude:bbbb", folder, home=tmp_path / "home").text
    with pytest.raises(ImportNotFound, match="0 Claude Code sessions start with 'zz'"):
        bring_in("claude:zz", folder, home=tmp_path / "home")
    with pytest.raises(ImportNotFound, match="no Claude Code session"):
        bring_in("claude", tmp_path / "other", home=tmp_path / "home")
    with pytest.raises(ImportNotFound, match="not a source"):
        bring_in("cursor", folder)


async def test_the_host_starts_with_the_session_in_the_agents_notes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "app"
    folder.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "home"))
    keep(tmp_path / "home", folder, "aaaa1111", "migrate the database")
    settings = HostSettings(
        provider="fake",
        workspace=folder,
        data_dir=tmp_path / "data",
        room="r_import",
        import_from="claude",
    )
    host = await build_host(settings)
    try:
        events = [record.event for record in await host.store.read()]
    finally:
        await host.close()
    imported = [event for event in events if isinstance(event, BriefingImported)]
    assert len(imported) == 1
    assert imported[0].item.source == "Claude Code aaaa1111"
    assert "migrate the database" in imported[0].text


async def test_a_missing_session_stops_the_host_before_it_is_created(tmp_path: Path) -> None:
    settings = HostSettings(
        provider="fake",
        workspace=tmp_path,
        data_dir=tmp_path / "data",
        room="r_none",
        import_from="claude",
    )
    with pytest.raises(ConfigError, match="no Claude Code session"):
        await build_host(settings)
    assert not (tmp_path / "data" / "sessions" / "r_none.db").exists()
