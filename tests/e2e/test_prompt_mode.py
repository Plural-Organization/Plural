from pathlib import Path

import pytest

from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.client.connection import CommandRejected
from plural.protocol.commands import (
    ApprovalRespond,
    PolicyAdd,
    PromptModeSet,
    PromptSubmit,
    ProposalDecide,
)
from plural.protocol.envelope import ErrorCode
from plural.protocol.events import (
    ApprovalRequested,
    PolicyRuleAdded,
    PromptAccepted,
    PromptModeChanged,
    ProposalCreated,
    RunEnded,
    ToolEnded,
)
from plural.protocol.models import (
    ApprovalDecision,
    Origin,
    PolicyAction,
    PromptMode,
    ProposalDecision,
    Role,
)
from tests.e2e.support import Session, running_session


def echo_provider() -> FakeProvider:
    return FakeProvider([use_tool("bash", "c1", command="echo hello world"), reply("done")])


async def test_sessions_are_open_by_default(session: Session) -> None:
    guest = await session.guest("Alia")
    assert guest.client.projection.state.prompt_mode is PromptMode.OPEN


async def test_participant_prompt_runs_without_a_proposal(session: Session) -> None:
    owner = await session.owner()
    guest = await session.guest("Alia")

    await guest.client.send(PromptSubmit(text="check the notes"))
    accepted = await owner.next(PromptAccepted)

    assert accepted.provenance.origin is Origin.DIRECT
    assert accepted.provenance.initiator_role is Role.PARTICIPANT
    assert not any(isinstance(e, ProposalCreated) for e in owner.events)
    assert not owner.client.projection.state.proposals


async def test_tool_calls_from_open_prompts_still_need_the_host(session: Session) -> None:
    owner = await session.owner()
    guest = await session.guest("Alia")
    await guest.client.send(PromptSubmit(text="check the notes"))

    approval = (await owner.next(ApprovalRequested)).approval
    assert approval.provenance.initiator_role is Role.PARTICIPANT
    with pytest.raises(CommandRejected) as own_tool:
        await guest.client.send(
            ApprovalRespond(approval_id=approval.id, decision=ApprovalDecision.ONCE)
        )
    assert own_tool.value.error.code is ErrorCode.FORBIDDEN

    await owner.client.send(
        ApprovalRespond(approval_id=approval.id, decision=ApprovalDecision.ONCE)
    )
    assert (await guest.next(ToolEnded)).ok
    assert (await guest.next(RunEnded)).error is None


async def test_allow_rule_does_not_lift_the_taint_of_open_prompts(tmp_path: Path) -> None:
    async with running_session(tmp_path, relayed=False, provider=echo_provider()) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        await owner.client.send(PolicyAdd(tool="bash", pattern="echo *", action=PolicyAction.ALLOW))
        await owner.next(PolicyRuleAdded)

        await guest.client.send(PromptSubmit(text="say hello"))
        approval = (await owner.next(ApprovalRequested)).approval
        assert approval.call.subject == "echo hello world"
        await owner.client.send(
            ApprovalRespond(approval_id=approval.id, decision=ApprovalDecision.REJECT)
        )
        await owner.next(RunEnded)


async def test_viewer_cannot_prompt_in_open_mode(session: Session) -> None:
    viewer = await session.guest("Eve", Role.VIEWER)
    with pytest.raises(CommandRejected) as rejected:
        await viewer.client.send(PromptSubmit(text="hello"))
    assert rejected.value.error.code is ErrorCode.FORBIDDEN


async def test_host_switches_the_mode_and_everyone_sees_it(session: Session) -> None:
    owner = await session.owner()
    guest = await session.guest("Alia")

    await owner.client.send(PromptModeSet(mode=PromptMode.REVIEW))
    changed = await guest.next(PromptModeChanged)
    assert changed.mode is PromptMode.REVIEW
    assert guest.client.projection.state.prompt_mode is PromptMode.REVIEW

    await guest.client.send(PromptSubmit(text="check the notes"))
    proposal = (await owner.next(ProposalCreated)).proposal
    assert proposal.text == "check the notes"
    assert not any(isinstance(e, PromptAccepted) for e in owner.events)

    await owner.client.send(PromptModeSet(mode=PromptMode.OPEN))
    assert (await guest.next(PromptModeChanged)).mode is PromptMode.OPEN
    await guest.client.send(PromptSubmit(text="again"))
    assert (await owner.next(PromptAccepted)).provenance.origin is Origin.DIRECT


async def test_pending_proposals_survive_a_switch_to_open(review_session: Session) -> None:
    owner = await review_session.owner()
    guest = await review_session.guest("Alia")
    await guest.client.send(PromptSubmit(text="check the notes"))
    proposal = (await owner.next(ProposalCreated)).proposal

    await owner.client.send(PromptModeSet(mode=PromptMode.OPEN))
    await owner.next(PromptModeChanged)
    await owner.client.send(
        ProposalDecide(proposal_id=proposal.id, decision=ProposalDecision.APPROVE)
    )
    assert (await owner.next(PromptAccepted)).provenance.origin is Origin.PROPOSAL


async def test_only_the_host_can_switch_the_mode(session: Session) -> None:
    guest = await session.guest("Alia")
    with pytest.raises(CommandRejected) as rejected:
        await guest.client.send(PromptModeSet(mode=PromptMode.REVIEW))
    assert rejected.value.error.code is ErrorCode.FORBIDDEN
    assert guest.client.projection.state.prompt_mode is PromptMode.OPEN


async def test_switching_to_the_current_mode_changes_nothing(session: Session) -> None:
    owner = await session.owner()
    await owner.client.send(PromptModeSet(mode=PromptMode.OPEN))
    assert not any(isinstance(e, PromptModeChanged) for e in owner.events)


async def test_mode_survives_a_host_restart_unless_the_flag_overrides_it(tmp_path: Path) -> None:
    async with running_session(
        tmp_path, relayed=False, provider=echo_provider(), overrides={"prompt_mode": "review"}
    ) as first:
        owner = await first.owner()
        assert owner.client.projection.state.prompt_mode is PromptMode.REVIEW

    async with running_session(tmp_path, relayed=False, provider=echo_provider()) as second:
        owner = await second.owner()
        assert owner.client.projection.state.prompt_mode is PromptMode.REVIEW

    async with running_session(
        tmp_path, relayed=False, provider=echo_provider(), overrides={"prompt_mode": "open"}
    ) as third:
        owner = await third.owner()
        assert owner.client.projection.state.prompt_mode is PromptMode.OPEN
