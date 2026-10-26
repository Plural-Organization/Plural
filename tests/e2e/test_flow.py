import pytest

from plural.client.connection import CommandRejected
from plural.client.presenter import Line, history
from plural.client.reconnect import JoinLink, SessionClient
from plural.protocol.commands import (
    ApprovalRespond,
    ParticipantRevoke,
    PromptSubmit,
    ProposalDecide,
)
from plural.protocol.envelope import ErrorCode
from plural.protocol.events import (
    ApprovalRequested,
    PromptAccepted,
    ProposalCreated,
    RunEnded,
    SessionWelcome,
    ToolEnded,
)
from plural.protocol.models import ApprovalDecision, Origin, ProposalDecision, Role
from tests.e2e.support import CLIENT, Session, Watcher, refusal


async def run_to_completion(session: Session) -> tuple[Watcher, Watcher]:
    owner = await session.owner()
    guest = await session.guest("Alia")
    await guest.client.send(PromptSubmit(text="check the notes"))
    proposal = (await owner.next(ProposalCreated)).proposal
    await owner.client.send(
        ProposalDecide(proposal_id=proposal.id, decision=ProposalDecision.APPROVE)
    )
    approval = (await owner.next(ApprovalRequested)).approval
    await owner.client.send(
        ApprovalRespond(approval_id=approval.id, decision=ApprovalDecision.ONCE)
    )
    await owner.next(RunEnded)
    await guest.next(RunEnded)
    return owner, guest


async def test_guest_proposal_needs_host_decisions(review_session: Session) -> None:
    owner = await review_session.owner()
    guest = await review_session.guest("Alia")

    await guest.client.send(PromptSubmit(text="check the notes"))
    proposal = (await owner.next(ProposalCreated)).proposal

    with pytest.raises(CommandRejected) as own_approval:
        await guest.client.send(
            ProposalDecide(proposal_id=proposal.id, decision=ProposalDecision.APPROVE)
        )
    assert own_approval.value.error.code is ErrorCode.FORBIDDEN

    await owner.client.send(
        ProposalDecide(proposal_id=proposal.id, decision=ProposalDecision.APPROVE)
    )
    approval = (await owner.next(ApprovalRequested)).approval
    assert approval.provenance.origin is Origin.PROPOSAL

    with pytest.raises(CommandRejected) as own_tool:
        await guest.client.send(
            ApprovalRespond(approval_id=approval.id, decision=ApprovalDecision.ONCE)
        )
    assert own_tool.value.error.code is ErrorCode.FORBIDDEN

    await owner.client.send(
        ApprovalRespond(approval_id=approval.id, decision=ApprovalDecision.ONCE)
    )
    accepted = await guest.next(PromptAccepted)
    assert accepted.provenance.origin is Origin.PROPOSAL
    ended = await guest.next(ToolEnded)
    assert ended.ok
    assert "alpha" in ended.output
    assert (await guest.next(RunEnded)).error is None


async def test_every_client_converges_on_the_same_state(review_session: Session) -> None:
    owner, guest = await run_to_completion(review_session)
    assert owner.client.projection.state.transcript == guest.client.projection.state.transcript
    assert owner.client.projection.state.run is None


async def test_late_joiner_sees_tool_output_in_history(review_session: Session) -> None:
    await run_to_completion(review_session)
    late = await review_session.guest("Cleo")
    lines = history(late.client.projection.state)
    assert Line("bold", "Alia › check the notes") in lines
    assert any(line.text.startswith("⚙ bash cat notes.txt ✓") for line in lines)
    assert Line("green", "alpha\nbeta\n[exit 0]") in lines
    assert Line("", "All good.") in lines


async def test_viewer_cannot_submit_prompts(session: Session) -> None:
    viewer = await session.guest("Eve", Role.VIEWER)
    with pytest.raises(CommandRejected) as rejected:
        await viewer.client.send(PromptSubmit(text="rm -rf /"))
    assert rejected.value.error.code is ErrorCode.FORBIDDEN


async def test_invite_is_single_use(session: Session) -> None:
    invite = session.host.invites.create(Role.PARTICIPANT, 600)
    first = await session.watch(invite.link, "Alia")
    assert first.client.projection.me is not None

    second = SessionClient(JoinLink.parse(invite.link), name="Mallory", client=CLIENT)
    assert await refusal(second) is ErrorCode.UNAUTHORIZED


async def test_forged_token_is_rejected(session: Session) -> None:
    link = JoinLink.parse(f"{session.host.host_link.split('?')[0]}?token=forged")
    client = SessionClient(link, name="Mallory", client=CLIENT)
    assert await refusal(client) is ErrorCode.UNAUTHORIZED


async def test_revoked_guest_is_locked_out(session: Session) -> None:
    owner = await session.owner()
    guest = await session.guest("Alia")
    welcome = next(e for e in guest.events if isinstance(e, SessionWelcome))
    await owner.client.send(ParticipantRevoke(participant_id=welcome.participant.id))

    returning = SessionClient(
        JoinLink.parse(f"{session.host.host_link.split('?')[0]}?token={welcome.token}"),
        name="Alia",
        client=CLIENT,
    )
    assert await refusal(returning) is ErrorCode.UNAUTHORIZED


async def test_same_names_stay_distinguishable(session: Session) -> None:
    owner = await session.owner()
    await session.guest("Bek")
    await session.guest("Bek")
    ids = {p.id for p in owner.client.projection.state.participants.values() if p.name == "Bek"}
    assert len(ids) == 2
