import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from plural.agent.briefing import briefing_prompt
from plural.host.agent_run import AgentRun
from plural.host.ledger import ChangeLedger
from plural.host.repo import git_branch, git_dirty, git_head, repo_facts
from plural.protocol.commands import MAX_BRIEFING_CHARS

MAX_FILES = 30
TRUNCATED = "\n[the briefing was cut here to fit the size limit]"


@dataclass(frozen=True, slots=True)
class Written:
    text: str
    narrative: str


def facts_block(
    *,
    repo: str,
    branch: str | None,
    head: str | None,
    dirty: int | None,
    files: tuple[tuple[str, int, int], ...],
) -> str:
    where = [f"repository {repo}"]
    if branch:
        where.append(f"branch {branch}")
    if head:
        where.append(f"HEAD {head}")
    if dirty is not None:
        where.append(f"{dirty} file{'' if dirty == 1 else 's'} with uncommitted changes")
    lines = [" · ".join(where)]
    if files:
        lines.append("Files this session changed (from the tool log):")
        lines.extend(
            f"- {path}  +{added} \u2212{removed}" for path, added, removed in files[:MAX_FILES]
        )
        if len(files) > MAX_FILES:
            lines.append(f"- and {len(files) - MAX_FILES} more")
    else:
        lines.append("No file was changed in this session yet.")
    return "\n".join(lines)


def assemble(
    owner: str, when: datetime, as_of: int, facts: str, narrative: str, update: bool
) -> str:
    kind = "Update to the earlier briefing" if update else "Briefing"
    head = f"{kind} from {owner}'s session, as of event {as_of} ({when:%Y-%m-%d %H:%M} UTC)."
    body = narrative.strip() or "The agent has not done anything in this session yet."
    text = f"{head}\n\n{facts}\n\n{body}"
    if len(text) <= MAX_BRIEFING_CHARS:
        return text
    return text[: MAX_BRIEFING_CHARS - len(TRUNCATED)] + TRUNCATED


class BriefingService:
    def __init__(
        self,
        *,
        agent: AgentRun,
        ledger: ChangeLedger,
        workspace: Path,
        owner: str,
        scrub: Callable[[str], str],
    ) -> None:
        self._agent = agent
        self._ledger = ledger
        self._workspace = workspace
        self._owner = owner
        self._scrub = scrub
        self._earlier: dict[str, str] = {}

    async def write(
        self,
        requester: str,
        focus: str | None,
        update: bool,
        *,
        as_of: int,
        when: datetime,
        cancel: asyncio.Event,
    ) -> Written:
        earlier = self._earlier.get(requester) if update else None
        narrative = self._scrub(
            await self._agent.brief(briefing_prompt(focus, earlier), cancel=cancel)
        )
        repo = await repo_facts(self._workspace)
        branch, head, dirty = await asyncio.gather(
            git_branch(self._workspace), git_head(self._workspace), git_dirty(self._workspace)
        )
        facts = facts_block(
            repo=repo.repo_id or repo.name,
            branch=branch,
            head=head,
            dirty=dirty,
            files=self._ledger.files(),
        )
        self._earlier[requester] = narrative
        return Written(
            text=self._scrub(
                assemble(self._owner, when, as_of, facts, narrative, update=earlier is not None)
            ),
            narrative=narrative,
        )
