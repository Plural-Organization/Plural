from pathlib import Path

import pytest

from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.client.connection import CommandRejected
from plural.protocol.commands import (
    ApprovalRespond,
    PromptSubmit,
    QueueCancel,
    RunAbort,
)
from plural.protocol.envelope import ErrorCode
from plural.protocol.events import ApprovalRequested, PromptDequeued, RunEnded
from plural.protocol.models import ApprovalDecision, Delivery, DequeueReason
from tests.e2e.support import Session, Watcher, running_session


def waiting_provider() -> FakeProvider:
    return FakeProvider(
        [
            use_tool("bash", "c1", command="echo hello"),
            reply("first done"),
            reply("second done"),
            reply("third done"),
        ]
    )


async def hold_a_run(owner: Watcher) -> str:
    await owner.client.send(PromptSubmit(text="start"))
    approval = (await owner.next(ApprovalRequested)).approval
    return approval.id


async def test_prompts_sent_during_a_run_wait_in_the_queue(tmp_path: Path) -> None:
    async with running_session(tmp_path, relayed=False, provider=waiting_provider()) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        approval_id = await hold_a_run(owner)

        await guest.client.send(PromptSubmit(text="and then this"))
        await guest.client.send(PromptSubmit(text="and this", delivery=Delivery.FOLLOW_UP))
        queue = guest.client.projection.state.queue
        assert [(entry.text, entry.delivery) for entry in queue] == [
            ("and then this", Delivery.NOW),
            ("and this", Delivery.FOLLOW_UP),
        ]
        assert queue[0].author_id == guest.client.projection.me_id

        await owner.client.send(
            ApprovalRespond(approval_id=approval_id, decision=ApprovalDecision.ONCE)
        )
        await owner.next(RunEnded)
        assert owner.client.projection.state.queue == ()
        reasons = [e.reason for e in owner.events if isinstance(e, PromptDequeued)]
        assert reasons == [DequeueReason.DELIVERED, DequeueReason.DELIVERED]


async def test_the_author_and_the_host_can_cancel_a_queued_prompt(tmp_path: Path) -> None:
    async with running_session(tmp_path, relayed=False, provider=waiting_provider()) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        other = await session.guest("Bek")
        await hold_a_run(owner)
        await guest.client.send(PromptSubmit(text="mine"))
        await guest.client.send(PromptSubmit(text="also mine"))
        first, second = guest.client.projection.state.queue

        with pytest.raises(CommandRejected) as stranger:
            await other.client.send(QueueCancel(prompt_id=first.prompt_id))
        assert stranger.value.error.code is ErrorCode.FORBIDDEN

        await guest.client.send(QueueCancel(prompt_id=first.prompt_id))
        cancelled = await owner.next(PromptDequeued)
        assert (cancelled.prompt_id, cancelled.reason) == (first.prompt_id, DequeueReason.CANCELLED)

        await owner.client.send(QueueCancel(prompt_id=second.prompt_id))
        assert (await owner.next(PromptDequeued)).prompt_id == second.prompt_id
        assert owner.client.projection.state.queue == ()

        with pytest.raises(CommandRejected) as gone:
            await owner.client.send(QueueCancel(prompt_id=second.prompt_id))
        assert gone.value.error.code is ErrorCode.NOT_FOUND


async def test_a_prompt_that_already_reached_the_agent_cannot_be_cancelled(tmp_path: Path) -> None:
    async with running_session(tmp_path, relayed=False, provider=waiting_provider()) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        approval_id = await hold_a_run(owner)
        await guest.client.send(PromptSubmit(text="soon"))
        entry = guest.client.projection.state.queue[0]
        await owner.client.send(
            ApprovalRespond(approval_id=approval_id, decision=ApprovalDecision.ONCE)
        )
        await owner.next(PromptDequeued)
        with pytest.raises(CommandRejected) as late:
            await guest.client.send(QueueCancel(prompt_id=entry.prompt_id))
        assert late.value.error.code is ErrorCode.NOT_FOUND


async def test_aborting_the_run_drops_what_was_queued(tmp_path: Path) -> None:
    async with running_session(tmp_path, relayed=False, provider=waiting_provider()) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        await hold_a_run(owner)
        await guest.client.send(PromptSubmit(text="never runs"))
        await owner.client.send(RunAbort())
        await owner.next(RunEnded)
        dropped = await owner.next(PromptDequeued)
        assert dropped.reason is DequeueReason.DROPPED
        assert guest.client.projection.state.queue == ()


async def test_a_prompt_during_an_idle_session_is_never_queued(session: Session) -> None:
    guest = await session.guest("Alia")
    await guest.client.send(PromptSubmit(text="hello"))
    assert guest.client.projection.state.queue == ()
