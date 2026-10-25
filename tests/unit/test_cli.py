import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from plural.cli.main import app
from plural.protocol.events import ParticipantLeft
from plural.storage.sqlite_store import SqliteEventStore

runner = CliRunner()


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "PLURAL_PROVIDER", "PLURAL_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PLURAL_DATA_DIR", str(tmp_path / "data"))


def test_doctor_passes_with_the_demo_provider(tmp_path: Path) -> None:
    result = runner.invoke(app, ["doctor", "--workspace", str(tmp_path)])
    assert result.exit_code == 0
    assert "fake" in result.output


def test_doctor_fails_without_a_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PLURAL_PROVIDER", "anthropic")
    result = runner.invoke(app, ["doctor", "--workspace", str(tmp_path)])
    assert result.exit_code == 1
    assert "ANTHROPIC_API_KEY" in result.output


def test_doctor_accepts_the_vendor_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PLURAL_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert runner.invoke(app, ["doctor", "--workspace", str(tmp_path)]).exit_code == 0


def test_join_rejects_a_link_without_a_websocket_scheme() -> None:
    result = runner.invoke(app, ["join", "http://example.com/r_1"])
    assert result.exit_code == 2


def test_export_writes_one_line_per_event(tmp_path: Path) -> None:
    async def populate() -> None:
        store = await SqliteEventStore.open(tmp_path / "data" / "sessions" / "r_demo.db")
        for index in range(3):
            await store.append(
                ParticipantLeft(participant_id=f"p_{index}"),
                event_id=f"e_{index}",
                ts=datetime(2026, 10, 25, tzinfo=UTC),
                actor_id=None,
            )
        await store.close()

    asyncio.run(populate())
    out = tmp_path / "session.jsonl"
    result = runner.invoke(app, ["export", "r_demo", "--out", str(out)])
    assert result.exit_code == 0
    assert len(out.read_text().splitlines()) == 3
