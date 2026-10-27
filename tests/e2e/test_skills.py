from pathlib import Path

import pytest

from plural.agent import skills as skill_module
from plural.agent.providers.base import Stop, ToolCallReady, ToolCallRequest
from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.client.connection import CommandRejected
from plural.protocol.commands import ApprovalRespond, PromptSubmit, SkillsInstall, SkillsSearch
from plural.protocol.envelope import ErrorCode
from plural.protocol.events import (
    ApprovalRequested,
    ErrorRaised,
    RunEnded,
    SkillsChanged,
    SkillsFound,
    ToolEnded,
)
from plural.protocol.models import ApprovalDecision, SkillScope
from tests.e2e.support import running_session
from tests.unit.test_skills import REPO

SEARCH = (
    b'{"skills":[{"source":"vercel-labs/agent-skills","skillId":"deploy-to-vercel","installs":7}]}'
)


def fake_web(url: str, limit: int) -> bytes:
    if url.startswith(skill_module.SEARCH_URL):
        return SEARCH
    if url == skill_module.ARCHIVE_URL.format(repo="vercel-labs/agent-skills"):
        return REPO
    raise skill_module.SkillError(f"offline: {url}")


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(skill_module, "_fetch", fake_web)


async def test_the_host_finds_and_installs_a_skill_everyone_sees(tmp_path: Path) -> None:
    async with running_session(tmp_path, relayed=False, provider=FakeProvider()) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")

        await guest.client.send(SkillsSearch(query="deploy"))
        found = await guest.next(SkillsFound)
        assert [hit.package for hit in found.hits] == ["vercel-labs/agent-skills@deploy-to-vercel"]

        with pytest.raises(CommandRejected) as rejected:
            await guest.client.send(SkillsInstall(package="vercel-labs/agent-skills@deploy"))
        assert rejected.value.error.code is ErrorCode.FORBIDDEN

        await owner.client.send(SkillsInstall(package="vercel-labs/agent-skills@deploy"))
        changed = await guest.next(SkillsChanged)
        assert changed.added == ("deploy-to-vercel",)
        assert guest.client.projection.state.skills[0].scope is SkillScope.PROJECT
        assert (tmp_path / "ws" / ".agents" / "skills" / "deploy-to-vercel" / "SKILL.md").exists()

        await owner.client.send(SkillsInstall(package="vercel-labs/agent-skills@missing"))
        assert "no skill named missing" in (await owner.next(ErrorRaised)).message


async def test_the_agent_installs_a_skill_only_after_the_host_approves(tmp_path: Path) -> None:
    provider = FakeProvider(
        [
            use_tool("skill_install", "c1", package="vercel-labs/agent-skills@deploy"),
            reply("installed"),
            (
                ToolCallReady(
                    call=ToolCallRequest(id="c2", name="skill", args={"name": "deploy-to-vercel"})
                ),
                Stop(reason="tool_use"),
            ),
            reply("loaded"),
        ]
    )
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        await owner.client.send(PromptSubmit(text="add a deploy skill"))
        approval = (await owner.next(ApprovalRequested)).approval
        assert approval.call.subject == "vercel-labs/agent-skills@deploy"
        await owner.client.send(
            ApprovalRespond(approval_id=approval.id, decision=ApprovalDecision.ONCE)
        )
        assert (await owner.next(SkillsChanged)).added == ("deploy-to-vercel",)
        assert (await owner.next(ToolEnded)).ok
        await owner.next(RunEnded)

        await owner.client.send(PromptSubmit(text="use it"))
        loaded = await owner.next(ToolEnded)
        await owner.next(RunEnded)
        assert loaded.ok
        assert "# deploy-to-vercel" in loaded.output
        assert "deploy-to-vercel: Does things." in provider.requests[-1].system
