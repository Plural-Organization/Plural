"""Sub-agents: short-lived loops the main agent hands a task to.

An agent is a Markdown file with a name, a description, the model role it runs on, the tools it
may use and its instructions, in the format Claude Code uses for `.claude/agents`. The host finds
them next to skills; `explore` is built in.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from plural.agent.skills import NAME, frontmatter
from plural.protocol.models import AgentView, SkillScope

AGENT_DIRS: Final = ((".agents", "agents"), (".claude", "agents"), (".plural", "agents"))
DEFAULT_TURNS: Final = 20
MAX_TURNS: Final = 50
MAX_DESCRIPTION: Final = 300

Role = Literal["fast", "main"]

# Claude Code names its tools differently; these are the ones Plural has.
TOOL_NAMES: Final = {
    "read": "read",
    "grep": "grep",
    "glob": "glob",
    "ls": "ls",
    "bash": "bash",
    "edit": "edit",
    "multiedit": "multi_edit",
    "multi_edit": "multi_edit",
    "write": "write",
    "webfetch": "web_fetch",
    "web_fetch": "web_fetch",
    "websearch": "web_search",
    "web_search": "web_search",
    "skill": "skill",
}
READ_ONLY: Final = ("read", "grep", "glob", "ls", "web_search", "web_fetch", "skill")

EXPLORE_PROMPT: Final = """\
You are explore, a read-only research agent working for another agent in a shared Plural session.

- You get one task. Investigate it with the read-only tools you have, then answer and stop.
- Search broadly first (glob, grep, ls), then read only the parts that matter. Call several \
read-only tools in the same turn: they run in parallel.
- You cannot change anything. Never suggest that you did.
- Your final message is the whole report: lead with the answer, then the evidence. Cite every \
claim as path:line. Say plainly what you could not find or did not check.
- Keep the report short and concrete; the other agent reads it, not a person."""


class AgentError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class AgentSpec:
    name: str
    description: str
    prompt: str
    role: Role = "fast"
    tools: tuple[str, ...] = READ_ONLY
    max_turns: int = DEFAULT_TURNS
    scope: SkillScope | None = None

    path: Path | None = None

    @property
    def read_only(self) -> bool:
        return all(tool in READ_ONLY for tool in self.tools)

    def view(self) -> AgentView:
        return AgentView(
            name=self.name,
            description=self.description,
            role=self.role,
            tools=self.tools,
            scope=self.scope,
            read_only=self.read_only,
        )

    def markdown(self) -> str:
        header = (
            f"name: {self.name}",
            f"description: {self.description}",
            f"tools: {', '.join(self.tools)}",
            f"model: {self.role}",
            f"max_turns: {self.max_turns}",
        )
        return "---\n" + "\n".join(header) + f"\n---\n\n{self.prompt.strip()}\n"


EXPLORE: Final = AgentSpec(
    name="explore",
    description=(
        "Broad read-only research across the codebase or the web: finding where something lives, "
        "how a flow works, every place a name is used. Returns findings with path:line. Use it "
        "instead of many reads of your own when the answer needs looking through many files."
    ),
    prompt=EXPLORE_PROMPT,
)


def agent_tools(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return READ_ONLY
    names = [part.strip().lower().replace(" ", "") for part in re.split(r"[,\[\]]", raw)]
    picked = tuple(dict.fromkeys(TOOL_NAMES[name] for name in names if name in TOOL_NAMES))
    return picked or READ_ONLY


def _role(raw: str | None) -> Role:
    value = (raw or "").strip().lower()
    return "fast" if value in {"", "fast", "haiku", "mini", "flash"} else "main"


def _turns(raw: str | None) -> int:
    try:
        return max(1, min(MAX_TURNS, int(raw or DEFAULT_TURNS)))
    except ValueError:
        return DEFAULT_TURNS


def read_agent(path: Path, scope: SkillScope) -> AgentSpec | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    fields = frontmatter(text)
    name = fields.get("name") or path.stem
    if not NAME.match(name):
        return None
    body = (
        text.split("---", 2)[2].strip()
        if text.startswith("---") and text.count("---") >= 2
        else text
    )
    description = " ".join(fields.get("description", "").split())[:MAX_DESCRIPTION]
    if not body or not description:
        return None
    return AgentSpec(
        name=name,
        description=description,
        prompt=body,
        role=_role(fields.get("model")),
        tools=agent_tools(fields.get("tools")),
        max_turns=_turns(fields.get("max_turns")),
        scope=scope,
        path=path,
    )


class AgentLibrary:
    def __init__(self, *, project: Path, home: Path) -> None:
        self._roots = (
            *((project.joinpath(*parts), SkillScope.PROJECT) for parts in AGENT_DIRS),
            *((home.joinpath(*parts), SkillScope.GLOBAL) for parts in AGENT_DIRS),
        )
        self._agents: dict[str, AgentSpec] = {EXPLORE.name: EXPLORE}
        self._targets = {
            SkillScope.PROJECT: project.joinpath(*AGENT_DIRS[0]),
            SkillScope.GLOBAL: home.joinpath(*AGENT_DIRS[0]),
        }

    @property
    def agents(self) -> tuple[AgentSpec, ...]:
        return tuple(self._agents.values())

    def get(self, name: str) -> AgentSpec | None:
        return self._agents.get(name)

    def refresh(self) -> tuple[AgentSpec, ...]:
        found: dict[str, AgentSpec] = {}
        for root, scope in self._roots:
            try:
                files = sorted(path for path in root.glob("*.md") if path.is_file())
            except OSError:
                continue
            for path in files:
                spec = read_agent(path, scope)
                if spec is not None and spec.name not in found:
                    found[spec.name] = spec
        self._agents = {EXPLORE.name: EXPLORE} | found
        return self.agents

    def describe(self) -> str | None:
        return describe(self.agents)

    def views(self) -> tuple[AgentView, ...]:
        return tuple(agent.view() for agent in self._agents.values())

    def create(self, spec: AgentSpec, scope: SkillScope) -> AgentSpec:
        if not NAME.match(spec.name):
            raise AgentError("a name is letters, digits, ., - and _, up to 64 characters")
        if spec.name in self._agents:
            raise AgentError(f"there is already an agent named {spec.name}")
        if not spec.description.strip() or not spec.prompt.strip():
            raise AgentError("an agent needs a description and instructions")
        folder = self._targets[scope]
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{spec.name}.md"
        path.write_text(spec.markdown(), encoding="utf-8")
        self.refresh()
        return self._agents[spec.name]

    def remove(self, name: str) -> None:
        spec = self._agents.get(name)
        if spec is None:
            raise AgentError(f"no agent named {name}")
        if spec.path is None:
            raise AgentError(f"{name} is built in")
        if spec.path.parent not in self._targets.values():
            raise AgentError(f"{name} lives in {spec.path.parent}; remove it there by hand")
        spec.path.unlink(missing_ok=True)
        self.refresh()


def describe(agents: Sequence[AgentSpec]) -> str | None:
    if not agents:
        return None
    lines = [f"- {agent.name}: {agent.description}" for agent in agents]
    return "\n".join(
        (
            "# Sub-agents",
            "The agent tool hands a task to a sub-agent that works in its own context, often on a "
            "cheaper model, and returns a short report. Delegate broad searches and research to it "
            "instead of reading many files yourself; give it a complete, self-contained task. "
            "Several calls in one turn run in parallel. Check the lines a report cites before you "
            "change code based on it.",
            *lines,
        )
    )
