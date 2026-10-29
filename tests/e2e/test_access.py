import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest

from plural.agent.providers.fake import FakeProvider, reply
from plural.client.connection import CommandRejected
from plural.protocol.commands import (
    AccessDecide,
    AccessRequest,
    ParticipantSetRole,
    PromptSubmit,
)
from plural.protocol.envelope import ErrorCode
from plural.protocol.events import (
    AccessRequested,
    AccessResolved,
    ParticipantRoleChanged,
    PromptAccepted,
    RunEnded,
)
from plural.protocol.models import AccessDecision, Role
from tests.e2e.support import Session, Watcher, running_session


@pytest.fixture
async def room(tmp_path: Path) -> AsyncGenerator[Session]:
    async with running_session(
        tmp_path, relayed=False, provider=FakeProvider([reply("done"), reply("again")])
    ) as running:
        yield running


async def rejected(call: object) -> ErrorCode:
    with pytest.raises(CommandRejected) as caught:
        await call  # type: ignore[misc]
    return caught.value.error.code


async def settle() -> None:
    await asyncio.sleep(0.3)


def seen(watcher: Watcher) -> list[AccessRequested]:
    return [event for event in watcher.events if isinstance(event, AccessRequested)]


async def test_a_viewer_asks_and_the_host_lets_them_write(room: Session) -> None:
    owner = await room.owner()
    cleo = await room.guest("Cleo", Role.VIEWER)
    bek = await room.guest("Bek", Role.VIEWER)
    assert await rejected(cleo.client.send(PromptSubmit(text="hi"))) is ErrorCode.FORBIDDEN

    await cleo.client.send(AccessRequest(note="I can fix the test"))
    asked = await owner.next(AccessRequested)
    assert asked.request.name == "Cleo"
    assert asked.request.note == "I can fix the test"
    await cleo.next(AccessRequested)
    await settle()
    assert seen(bek) == []
    assert list(owner.client.projection.state.access_requests) == [asked.request.participant_id]

    await owner.client.send(
        AccessDecide(participant_id=asked.request.participant_id, decision="allow")
    )
    resolved = await cleo.next(AccessResolved)
    assert resolved.decision is AccessDecision.GRANTED
    changed = await cleo.next(ParticipantRoleChanged)
    assert changed.role is Role.PARTICIPANT
    assert owner.client.projection.state.access_requests == {}

    await cleo.client.send(PromptSubmit(text="try the fix"))
    accepted = await owner.next(PromptAccepted)
    assert accepted.author_id == asked.request.participant_id
    assert accepted.provenance.initiator_role is Role.PARTICIPANT
    await owner.next(RunEnded)


async def test_a_refusal_is_told_and_the_person_must_wait_to_ask_again(room: Session) -> None:
    owner = await room.owner()
    cleo = await room.guest("Cleo", Role.VIEWER)
    await cleo.client.send(AccessRequest())
    asked = await owner.next(AccessRequested)
    await owner.client.send(
        AccessDecide(participant_id=asked.request.participant_id, decision="deny")
    )
    resolved = await cleo.next(AccessResolved)
    assert resolved.decision is AccessDecision.DENIED
    assert cleo.client.projection.me is not None
    assert cleo.client.projection.me.role is Role.VIEWER
    assert await rejected(cleo.client.send(AccessRequest())) is ErrorCode.CONFLICT


async def test_asking_twice_at_once_and_asking_when_you_can_write_are_refused(
    room: Session,
) -> None:
    owner = await room.owner()
    cleo = await room.guest("Cleo", Role.VIEWER)
    alia = await room.guest("Alia", Role.PARTICIPANT)
    await cleo.client.send(AccessRequest())
    await owner.next(AccessRequested)
    assert await rejected(cleo.client.send(AccessRequest())) is ErrorCode.CONFLICT
    assert await rejected(alia.client.send(AccessRequest())) is ErrorCode.CONFLICT


async def test_only_the_host_answers(room: Session) -> None:
    owner = await room.owner()
    cleo = await room.guest("Cleo", Role.VIEWER)
    alia = await room.guest("Alia", Role.PARTICIPANT)
    await cleo.client.send(AccessRequest())
    asked = await owner.next(AccessRequested)
    decide = AccessDecide(participant_id=asked.request.participant_id, decision="allow")
    assert await rejected(alia.client.send(decide)) is ErrorCode.FORBIDDEN
    assert await rejected(cleo.client.send(decide)) is ErrorCode.FORBIDDEN


async def test_answering_a_request_that_is_gone_is_not_found(room: Session) -> None:
    owner = await room.owner()
    cleo = await room.guest("Cleo", Role.VIEWER)
    await cleo.client.send(AccessRequest())
    asked = await owner.next(AccessRequested)
    person = asked.request.participant_id
    await owner.client.send(ParticipantSetRole(participant_id=person, role=Role.PARTICIPANT))
    await owner.next(ParticipantRoleChanged)
    assert (
        await rejected(owner.client.send(AccessDecide(participant_id=person, decision="allow")))
        is ErrorCode.NOT_FOUND
    )


async def test_a_newcomer_sees_no_requests_but_their_own(room: Session) -> None:
    owner = await room.owner()
    cleo = await room.guest("Cleo", Role.VIEWER)
    await cleo.client.send(AccessRequest())
    await owner.next(AccessRequested)
    bek = await room.guest("Bek", Role.VIEWER)
    await settle()
    assert bek.client.projection.state.access_requests == {}
    late = await room.watch(room.host.invites.create(Role.VIEWER, 600).link, "Dana")
    await settle()
    assert late.client.projection.state.access_requests == {}
