from pathlib import Path

import pytest
from pydantic import SecretStr

from plural.agent.agents import EXPLORE, AgentError, AgentLibrary, AgentSpec
from plural.core.state import reduce
from plural.host.config import HostSettings
from plural.host.control import AgentConfig, settings_for
from plural.host.routing import build_helper
from plural.protocol.events import EventRecord, UsageRecorded
from plural.protocol.models import SessionState, SkillScope, Usage, UsageLine

TS = "2026-10-28T00:00:00Z"


def record(seq: int, *lines: UsageLine) -> EventRecord:
    return EventRecord.model_validate(
        {
            "seq": seq,
            "id": f"e{seq}",
            "ts": TS,
            "actor_id": None,
            "event": UsageRecorded(lines=lines),
        }
    )


def test_usage_adds_up_by_role_model_and_agent() -> None:
    main = UsageLine(
        role="main", model="opus", uses=1, usage=Usage(input_tokens=100, output_tokens=10)
    )
    explore = UsageLine(
        role="fast", model="haiku", agent="explore", uses=1, usage=Usage(input_tokens=50)
    )
    state = reduce(SessionState(), record(1, main, explore))
    state = reduce(state, record(2, main))
    by_key = {(line.role, line.agent): line for line in state.usage}
    assert by_key[("main", "")].uses == 2
    assert by_key[("main", "")].usage == Usage(input_tokens=200, output_tokens=20)
    assert by_key[("fast", "explore")].usage.input_tokens == 50


def test_agents_are_created_as_files_and_only_ours_can_be_removed(tmp_path: Path) -> None:
    library = AgentLibrary(project=tmp_path / "ws", home=tmp_path / "home")
    library.refresh()
    spec = AgentSpec(
        name="reviewer", description="Reviews diffs.", prompt="Review it.", role="main"
    )
    created = library.create(spec, SkillScope.PROJECT)
    path = tmp_path / "ws" / ".agents" / "agents" / "reviewer.md"
    assert created.path == path
    assert "model: main" in path.read_text()
    assert [view.name for view in library.views()] == ["explore", "reviewer"]

    with pytest.raises(AgentError, match="already"):
        library.create(spec, SkillScope.GLOBAL)
    with pytest.raises(AgentError, match="built in"):
        library.remove(EXPLORE.name)
    library.remove("reviewer")
    assert not path.exists()
    assert [view.name for view in library.views()] == ["explore"]


def test_the_fast_model_can_be_chosen_or_switched_off_from_the_settings() -> None:
    base = HostSettings(provider="fake")
    chosen = AgentConfig(
        provider="anthropic",
        api_key=SecretStr("sk-ant-test-1234567"),
        fast_model="claude-sonnet-5-5",
    )
    helper = build_helper(settings_for(base, chosen), {})
    assert helper is not None
    assert helper.label == "claude-sonnet-5-5"

    auto = AgentConfig(
        provider="anthropic", api_key=SecretStr("sk-ant-test-1234567"), fast_model=""
    )
    helper = build_helper(settings_for(base, auto), {})
    assert helper is not None
    assert helper.label == "claude-haiku-5-5"
