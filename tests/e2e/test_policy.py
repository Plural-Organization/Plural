from pathlib import Path

import pytest

from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.client.connection import CommandRejected
from plural.protocol.commands import (
    ApprovalRespond,
    PolicyAdd,
    PolicyRemove,
    PromptSubmit,
    ProposalDecide,
)
from plural.protocol.envelope import ErrorCode
from plural.protocol.events import (
    ApprovalRequested,
    PolicyRuleAdded,
    PolicyRuleRemoved,
    ProposalCreated,
    RunEnded,
    ToolEnded,
)
from plural.protocol.models import ApprovalDecision, PolicyAction, ProposalDecision
from tests.e2e.support import Session, running_session


def echo_provider() -> FakeProvider:
    return FakeProvider([use_tool("bash", "c1", command="echo hello world"), reply("done")])


async def test_host_manages_rules_and_everyone_sees_them(session: Session) -> None:
    owner = await session.owner()
    guest = await session.guest("Alia")

    await owner.client.send(PolicyAdd(tool="bash", pattern="make *", action=PolicyAction.ALLOW))
    added = await guest.next(PolicyRuleAdded)
    assert added.rule.pattern == "make *"
    assert guest.client.projection.state.policy == (added.rule,)

    await owner.client.send(PolicyRemove(rule_id=added.rule.id))
    removed = await guest.next(PolicyRuleRemoved)
    assert removed.rule_id == added.rule.id
    assert guest.client.projection.state.policy == ()


async def test_guest_cannot_change_policy(session: Session) -> None:
    owner = await session.owner()
    guest = await session.guest("Alia")
    await owner.client.send(PolicyAdd(tool="bash", pattern="ls*", action=PolicyAction.ASK))
    rule = (await owner.next(PolicyRuleAdded)).rule

    with pytest.raises(CommandRejected) as widening:
        await guest.client.send(PolicyAdd(tool="*", pattern="*", action=PolicyAction.ALLOW))
    assert widening.value.error.code is ErrorCode.FORBIDDEN
    with pytest.raises(CommandRejected) as removal:
        await guest.client.send(PolicyRemove(rule_id=rule.id))
    assert removal.value.error.code is ErrorCode.FORBIDDEN


async def test_unknown_and_duplicate_rules_are_refused(session: Session) -> None:
    owner = await session.owner()
    with pytest.raises(CommandRejected) as unknown:
        await owner.client.send(PolicyRemove(rule_id="pl_missing"))
    assert unknown.value.error.code is ErrorCode.NOT_FOUND

    add = PolicyAdd(tool="bash", pattern="make *", action=PolicyAction.ALLOW)
    await owner.client.send(add)
    with pytest.raises(CommandRejected) as duplicate:
        await owner.client.send(add)
    assert duplicate.value.error.code is ErrorCode.INVALID


async def test_welcome_lists_the_built_in_rules(session: Session) -> None:
    guest = await session.guest("Alia")
    base = guest.client.projection.base_policy
    assert any(r.action is PolicyAction.DENY and r.pattern == "rm -rf*" for r in base)


async def test_always_becomes_a_visible_rule_and_stops_the_prompts(tmp_path: Path) -> None:
    provider = FakeProvider(
        [
            use_tool("bash", "c1", command="echo hello"),
            use_tool("bash", "c2", command="echo hello again"),
            reply("done"),
        ]
    )
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        await owner.client.send(PromptSubmit(text="say hello"))
        approval = (await owner.next(ApprovalRequested)).approval
        await owner.client.send(
            ApprovalRespond(approval_id=approval.id, decision=ApprovalDecision.ALWAYS)
        )
        await owner.next(RunEnded)

        rules = guest.client.projection.state.policy
        assert [(r.tool, r.pattern, r.action) for r in rules] == [
            ("bash", "echo hello*", PolicyAction.ALLOW)
        ]
        asked = [e for e in owner.events if isinstance(e, ApprovalRequested)]
        assert len(asked) == 1
        assert [e.ok for e in owner.events if isinstance(e, ToolEnded)] == [True, True]


async def test_rules_survive_a_host_restart(tmp_path: Path) -> None:
    async with running_session(tmp_path, relayed=False, provider=echo_provider()) as first:
        owner = await first.owner()
        await owner.client.send(PolicyAdd(tool="bash", pattern="echo *", action=PolicyAction.ALLOW))
        await owner.next(PolicyRuleAdded)

    async with running_session(tmp_path, relayed=False, provider=echo_provider()) as second:
        owner = await second.owner()
        assert len(owner.client.projection.state.policy) == 1
        await owner.client.send(PromptSubmit(text="say hello"))
        await owner.next(RunEnded)
        assert not any(isinstance(e, ApprovalRequested) for e in owner.events)
        assert [e.ok for e in owner.events if isinstance(e, ToolEnded)] == [True]


async def test_allow_rule_does_not_lift_the_guest_taint(tmp_path: Path) -> None:
    async with running_session(tmp_path, relayed=False, provider=echo_provider()) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        await owner.client.send(PolicyAdd(tool="bash", pattern="echo *", action=PolicyAction.ALLOW))
        await owner.next(PolicyRuleAdded)

        await guest.client.send(PromptSubmit(text="say hello"))
        proposal = (await owner.next(ProposalCreated)).proposal
        await owner.client.send(
            ProposalDecide(proposal_id=proposal.id, decision=ProposalDecision.APPROVE)
        )
        approval = (await owner.next(ApprovalRequested)).approval
        assert approval.call.subject == "echo hello world"
        await owner.client.send(
            ApprovalRespond(approval_id=approval.id, decision=ApprovalDecision.REJECT)
        )
        await owner.next(RunEnded)


async def test_allow_rule_cannot_override_a_built_in_deny(tmp_path: Path) -> None:
    provider = FakeProvider([use_tool("bash", "c1", command="rm -rf /tmp/x"), reply("done")])
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        await owner.client.send(PolicyAdd(tool="bash", pattern="*", action=PolicyAction.ALLOW))
        await owner.next(PolicyRuleAdded)

        await owner.client.send(PromptSubmit(text="clean up"))
        ended = await owner.next(ToolEnded)
        assert not ended.ok
        assert "denied by policy rule" in ended.output
        assert not any(isinstance(e, ApprovalRequested) for e in owner.events)
