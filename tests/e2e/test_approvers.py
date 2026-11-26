from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from plural.client.connection import CommandRejected
from plural.protocol.commands import (
    ApprovalRespond,
    ApproverSet,
    ParticipantSetRole,
    PromptSubmit,
)
from plural.protocol.envelope import ErrorCode
from plural.protocol.events import (
    ApprovalRequested,
    ApprovalResolved,
    ApproverChanged,
    RunEnded,
    ToolEnded,
)
from plural.protocol.models import ApprovalDecision, Role
from tests.doubles import FakeProvider, reply, use_tool
from tests.e2e.support import Session, running_session


def two_runs() -> FakeProvider:
    return FakeProvider(
        [
            use_tool("bash", "c1", command="echo hello"),
            reply("done"),
            use_tool("bash", "c2", command="echo again"),
            reply("done again"),
        ]
    )


@pytest.fixture
async def room(tmp_path: Path) -> AsyncGenerator[Session]:
    async with running_session(tmp_path, relayed=False, provider=two_runs()) as running:
        yield running


async def refused(call: object) -> ErrorCode:
    with pytest.raises(CommandRejected) as caught:
        await call  # type: ignore[misc]
    return caught.value.error.code


async def test_the_host_names_an_approver_and_everyone_sees_it(room: Session) -> None:
    owner = await room.owner()
    bek = await room.guest("Bek")
    assert bek.client.projection.me is not None
    bek_id = bek.client.projection.me.id

    await owner.client.send(ApproverSet(participant_id=bek_id, enabled=True))
    changed = await bek.next(ApproverChanged)
    assert (changed.participant_id, changed.enabled) == (bek_id, True)
    assert owner.client.projection.state.approvers == (bek_id,)
    assert bek.client.projection.state.approvers == (bek_id,)

    await owner.client.send(ApproverSet(participant_id=bek_id, enabled=False))
    assert (await bek.next(ApproverChanged)).enabled is False
    assert bek.client.projection.state.approvers == ()


async def test_a_guest_cannot_name_an_approver(room: Session) -> None:
    owner = await room.owner()
    alia = await room.guest("Alia")
    bek = await room.guest("Bek")
    assert bek.client.projection.me is not None
    bek_id = bek.client.projection.me.id

    code = await refused(alia.client.send(ApproverSet(participant_id=bek_id, enabled=True)))
    assert code is ErrorCode.FORBIDDEN
    assert owner.client.projection.state.approvers == ()


async def test_only_a_participant_can_be_named_and_the_person_must_exist(room: Session) -> None:
    owner = await room.owner()
    cleo = await room.guest("Cleo", Role.VIEWER)
    assert cleo.client.projection.me is not None

    viewer = ApproverSet(participant_id=cleo.client.projection.me.id, enabled=True)
    assert await refused(owner.client.send(viewer)) is ErrorCode.INVALID
    nobody = ApproverSet(participant_id="p_nobody", enabled=True)
    assert await refused(owner.client.send(nobody)) is ErrorCode.NOT_FOUND


async def test_an_approver_lets_a_tool_run_for_someone_else_while_the_host_is_away(
    room: Session,
) -> None:
    owner = await room.owner()
    alia = await room.guest("Alia")
    bek = await room.guest("Bek")
    assert bek.client.projection.me is not None
    await owner.client.send(ApproverSet(participant_id=bek.client.projection.me.id, enabled=True))
    await bek.next(ApproverChanged)

    await alia.client.send(PromptSubmit(text="say hello"))
    asked = (await bek.next(ApprovalRequested)).approval
    await bek.client.send(ApprovalRespond(approval_id=asked.id, decision=ApprovalDecision.ONCE))

    resolved = await owner.next(ApprovalResolved)
    assert resolved.decision is ApprovalDecision.ONCE
    assert resolved.resolved_by == bek.client.projection.me.id
    await owner.next(RunEnded)
    assert [e.ok for e in owner.events if isinstance(e, ToolEnded)] == [True]


async def test_an_approver_cannot_approve_their_own_prompt_or_make_a_rule(room: Session) -> None:
    owner = await room.owner()
    bek = await room.guest("Bek")
    assert bek.client.projection.me is not None
    await owner.client.send(ApproverSet(participant_id=bek.client.projection.me.id, enabled=True))
    await bek.next(ApproverChanged)

    await bek.client.send(PromptSubmit(text="say hello"))
    asked = (await owner.next(ApprovalRequested)).approval
    own = ApprovalRespond(approval_id=asked.id, decision=ApprovalDecision.ONCE)
    assert await refused(bek.client.send(own)) is ErrorCode.FORBIDDEN
    assert owner.client.projection.state.policy == ()

    await owner.client.send(ApprovalRespond(approval_id=asked.id, decision=ApprovalDecision.REJECT))
    await owner.next(RunEnded)


async def test_a_guest_who_was_not_named_cannot_answer(room: Session) -> None:
    owner = await room.owner()
    alia = await room.guest("Alia")
    bek = await room.guest("Bek")

    await alia.client.send(PromptSubmit(text="say hello"))
    asked = (await owner.next(ApprovalRequested)).approval
    answer = ApprovalRespond(approval_id=asked.id, decision=ApprovalDecision.ONCE)
    assert await refused(bek.client.send(answer)) is ErrorCode.FORBIDDEN
    assert await refused(alia.client.send(answer)) is ErrorCode.FORBIDDEN
    assert not any(isinstance(e, ToolEnded) for e in owner.events)

    await owner.client.send(ApprovalRespond(approval_id=asked.id, decision=ApprovalDecision.REJECT))
    await owner.next(RunEnded)


async def test_an_approver_who_loses_the_right_to_write_can_no_longer_answer(room: Session) -> None:
    owner = await room.owner()
    alia = await room.guest("Alia")
    bek = await room.guest("Bek")
    assert bek.client.projection.me is not None
    bek_id = bek.client.projection.me.id
    await owner.client.send(ApproverSet(participant_id=bek_id, enabled=True))
    await bek.next(ApproverChanged)
    await owner.client.send(ParticipantSetRole(participant_id=bek_id, role=Role.VIEWER))
    await alia.client.send(PromptSubmit(text="say hello"))
    asked = (await owner.next(ApprovalRequested)).approval

    assert owner.client.projection.state.approvers == ()
    answer = ApprovalRespond(approval_id=asked.id, decision=ApprovalDecision.ONCE)
    assert await refused(bek.client.send(answer)) is ErrorCode.FORBIDDEN
    await owner.client.send(ApprovalRespond(approval_id=asked.id, decision=ApprovalDecision.REJECT))
    await owner.next(RunEnded)
