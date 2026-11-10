from datetime import date
from pathlib import Path

from plural.agent.context.context import ContextBuilder, Environment
from plural.agent.tools.registry import builtin_tools


def test_system_prompt_describes_the_room_environment_and_project() -> None:
    environment = Environment(
        workspace=Path("/work/app"),
        today=date(2026, 10, 27),
        git_branch="main",
        system="Darwin",
        release="24.6.0",
        machine="arm64",
    )
    system = ContextBuilder(environment=environment, project_notes="Run make test.").system()

    assert "shared Plural session" in system
    assert "- Workspace: /work/app" in system
    assert "- Platform: Darwin 24.6.0 (arm64)" in system
    assert "- Git: branch main" in system
    assert "- Session started on 2026-10-27" in system
    assert system.endswith('<project_notes path="AGENTS.md">\nRun make test.\n</project_notes>')


def test_system_prompt_is_stable_for_prompt_caching() -> None:
    environment = Environment(workspace=Path("/w"), today=date(2026, 1, 1))
    builder = ContextBuilder(environment=environment)
    assert builder.system() == builder.system()
    assert "not a git repository" in builder.system()


def test_tool_rules_follow_the_how_to_work_list() -> None:
    system = ContextBuilder(tool_rules=("Use write only for new files.",)).system()
    assert "- Never print or copy secrets" in system
    assert system.endswith("<tool_rules>\n- Use write only for new files.\n</tool_rules>")


def test_only_tools_declared_up_front_bring_rules() -> None:
    rules = builtin_tools().guidelines()
    assert "Use write only for new files or full rewrites." in rules
    assert len(rules) == len(set(rules))
