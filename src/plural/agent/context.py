import platform
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Final, Protocol

from plural.agent.prompts import prompt, tag

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

    def system(self) -> str:
        parts = [self.system_prompt]
        if self.tool_rules:
            parts.append(tag("tool_rules", "\n".join(f"- {rule}" for rule in self.tool_rules)))
        if self.environment is not None:
            parts.append(self.environment.describe())
        if self.project_notes:
            parts.append(tag("project_notes", self.project_notes, path="AGENTS.md"))
        for catalog in (self.skills, self.agents):
            if catalog is not None and (text := catalog.describe()):
                parts.append(text)
        return "\n\n".join(parts)
