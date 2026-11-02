import platform
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final, Protocol

from plural.agent.prompts import prompt, tag
from plural.protocol.models import ContextPartKind

DEFAULT_SYSTEM_PROMPT: Final = prompt("system")


@dataclass(frozen=True, slots=True)
class Environment:
    workspace: Path
    today: date
    git_branch: str | None = None
    system: str = platform.system()
    release: str = platform.release()
    machine: str = platform.machine()

    def describe(self) -> str:
        git = (
            "not a git repository"
            if self.git_branch is None
            else self.git_branch
            if self.git_branch == "detached HEAD"
            else f"branch {self.git_branch}"
        )
        return tag(
            "environment",
            "\n".join(
                (
                    f"- Workspace: {self.workspace}",
                    f"- Platform: {self.system} {self.release} ({self.machine})",
                    "- Shell: commands run with bash -lc in the workspace and a minimal "
                    "environment",
                    f"- Git: {git}",
                    f"- Session started on {self.today.isoformat()}",
                )
            ),
        )


class SkillCatalog(Protocol):
    def describe(self) -> str | None: ...


@dataclass(frozen=True, slots=True)
class ContextBuilder:
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    environment: Environment | None = None
    project_notes: str | None = None
    skills: SkillCatalog | None = None
    agents: SkillCatalog | None = None
    # The declared tools' own rules, as in pi.
    tool_rules: tuple[str, ...] = ()

    def sections(self) -> tuple[tuple[ContextPartKind, str], ...]:
        """The system prompt's parts in order, each with what it is."""
        parts = [(ContextPartKind.SYSTEM, self.system_prompt)]
        if self.tool_rules:
            rules = tag("tool_rules", "\n".join(f"- {rule}" for rule in self.tool_rules))
            parts.append((ContextPartKind.TOOL_RULES, rules))
        if self.environment is not None:
            parts.append((ContextPartKind.ENVIRONMENT, self.environment.describe()))
        if self.project_notes:
            notes = tag("project_notes", self.project_notes, path="AGENTS.md")
            parts.append((ContextPartKind.PROJECT_NOTES, notes))
        for kind, catalog in (
            (ContextPartKind.SKILLS, self.skills),
            (ContextPartKind.AGENTS, self.agents),
        ):
            if catalog is not None and (text := catalog.describe()):
                parts.append((kind, text))
        return tuple(parts)

    def system(self) -> str:
        return system_text(self.sections())


def system_text(sections: Iterable[tuple[ContextPartKind, str]]) -> str:
    return "\n\n".join(text for _, text in sections)
