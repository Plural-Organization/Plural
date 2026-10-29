import asyncio
from collections.abc import AsyncGenerator
from datetime import timedelta
from pathlib import Path

import pytest

from plural.agent.messages import NOTES_HEADER
from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.client.connection import CommandRejected
from plural.client.reconnect import JoinLink, SessionClient
from plural.core import briefings
from plural.host.bootstrap import build_host
from plural.host.config import HostSettings
from plural.protocol.commands import (
    ApprovalRespond,
    BriefingDecide,
    BriefingImport,
    BriefingRequest,
    BriefingSharingSet,
    PermissionModeSet,
    PromptSubmit,
)
from plural.protocol.envelope import ErrorCode
from plural.protocol.events import (
    ApprovalRequested,
    BriefingDelivered,
    BriefingImported,
    BriefingRequested,
    BriefingResolved,
    BriefingSharingChanged,
    PermissionModeChanged,
    RunEnded,
    SessionSnapshot,
)
from plural.protocol.models import (
    ApprovalDecision,
    BriefingDecision,
    BriefingSharing,
    PermissionMode,
    Role,
)
from tests.e2e.support import CLIENT, Session, Watcher, free_port, running_session

BRIEFING = "<briefing>Goal: fix login. Done: added a retry in login.py. Open: the test.</briefing>"


@pytest.fixture(autouse=True)
def no_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(briefings, "COOLDOWN", timedelta(0))


def worked(*extra: tuple[object, ...]) -> FakeProvider:
    return FakeProvider(
        [
            use_tool("write", "c1", path="login.py", content="retry()\n"),
            reply("I added a retry"),
            *extra,  # type: ignore[arg-type]
        ]
    )


async def worked_session(session: Session) -> Watcher:
    owner = await session.owner()
    await owner.client.send(PromptSubmit(text="fix the login"))
    approval = (await owner.next(ApprovalRequested)).approval
    await owner.client.send(
        ApprovalRespond(approval_id=approval.id, decision=ApprovalDecision.ONCE)
    )
    await owner.next(RunEnded)
    return owner


async def rejected(call: object) -> ErrorCode:
    with pytest.raises(CommandRejected) as caught:
        await call  # type: ignore[misc]
    return caught.value.error.code


@pytest.fixture
async def room(tmp_path: Path) -> AsyncGenerator[tuple[Session, FakeProvider]]:
    provider = worked(reply(BRIEFING), reply(BRIEFING), reply(BRIEFING))
    async with running_session(tmp_path, relayed=False, provider=provider) as running:
        yield running, provider


async def test_a_viewer_asks_the_host_agrees_and_a_briefing_with_facts_comes_back(
    room: tuple[Session, FakeProvider],
) -> None:
    session, provider = room
    owner = await worked_session(session)
    cleo = await session.guest("Cleo", Role.VIEWER)
    alia = await session.guest("Alia", Role.PARTICIPANT)

    await cleo.client.send(BriefingRequest(focus="how was the login fixed?"))
    asked = (await owner.next(BriefingRequested)).request
    assert (asked.name, asked.focus) == ("Cleo", "how was the login fixed?")
    await cleo.next(BriefingRequested)

    await owner.client.send(BriefingDecide(request_id=asked.id, decision="allow"))
    assert (await cleo.next(BriefingResolved)).decision is BriefingDecision.GRANTED
    delivered = await cleo.next(BriefingDelivered)

    assert delivered.error is None
    assert delivered.to == asked.participant_id
    assert delivered.text.startswith("Briefing from host's session, as of event")
    assert "login.py  +1" in delivered.text
    assert "Goal: fix login. Done: added a retry in login.py." in delivered.text
    assert delivered.as_of_seq > 0
    prompt = provider.requests[-1].messages[-1].content
    assert "<question>\nhow was the login fixed?\n</question>" in prompt
    await asyncio.sleep(0.2)
    assert not [event for event in alia.events if isinstance(event, BriefingDelivered)]
    assert not [event for event in alia.events if isinstance(event, BriefingRequested)]


async def test_a_refused_request_gets_no_briefing(room: tuple[Session, FakeProvider]) -> None:
    session, provider = room
    owner = await worked_session(session)
    cleo = await session.guest("Cleo", Role.VIEWER)
    await cleo.client.send(BriefingRequest())
    asked = (await owner.next(BriefingRequested)).request
    await owner.client.send(BriefingDecide(request_id=asked.id, decision="deny"))
    assert (await cleo.next(BriefingResolved)).decision is BriefingDecision.DENIED
    await asyncio.sleep(0.2)
    assert not [event for event in cleo.events if isinstance(event, BriefingDelivered)]
    assert len(provider.requests) == 2


async def test_when_the_host_shares_with_the_team_nobody_has_to_answer(
    room: tuple[Session, FakeProvider],
) -> None:
    session, _ = room
    owner = await worked_session(session)
    await owner.client.send(BriefingSharingSet(mode=BriefingSharing.TEAM))
    assert (await owner.next(BriefingSharingChanged)).mode is BriefingSharing.TEAM
    cleo = await session.guest("Cleo", Role.VIEWER)
    await cleo.client.send(BriefingRequest())
    assert (await cleo.next(BriefingResolved)).decision is BriefingDecision.GRANTED
    assert "Goal: fix login" in (await cleo.next(BriefingDelivered)).text


async def test_a_session_that_shares_nothing_refuses_and_only_the_host_changes_that(
    room: tuple[Session, FakeProvider],
) -> None:
    session, _ = room
    owner = await worked_session(session)
    cleo = await session.guest("Cleo", Role.VIEWER)
    assert (
        await rejected(cleo.client.send(BriefingSharingSet(mode=BriefingSharing.OFF)))
        is ErrorCode.FORBIDDEN
    )
    await owner.client.send(BriefingSharingSet(mode=BriefingSharing.OFF))
    await owner.next(BriefingSharingChanged)
    assert await rejected(cleo.client.send(BriefingRequest())) is ErrorCode.CONFLICT
    assert await rejected(owner.client.send(BriefingRequest())) is ErrorCode.FORBIDDEN


async def test_an_update_tells_the_model_what_the_reader_already_has(
    room: tuple[Session, FakeProvider],
) -> None:
    session, provider = room
    owner = await worked_session(session)
    await owner.client.send(BriefingSharingSet(mode=BriefingSharing.TEAM))
    await owner.next(BriefingSharingChanged)
    cleo = await session.guest("Cleo", Role.VIEWER)

    await cleo.client.send(BriefingRequest())
    first = await cleo.next(BriefingDelivered)
    assert "<earlier>" not in provider.requests[-1].messages[-1].content

    await cleo.client.send(BriefingRequest(update=True))
    second = await cleo.next(BriefingDelivered)
    prompt = provider.requests[-1].messages[-1].content
    assert (
        "<earlier>\nGoal: fix login. Done: added a retry in login.py. Open: the test.\n</earlier>"
        in prompt
    )
    assert second.text.startswith("Update to the earlier briefing")
    assert first.text.startswith("Briefing from")


async def test_a_model_that_cannot_write_it_says_so(tmp_path: Path) -> None:
    provider = worked(reply(""), reply(""))
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await worked_session(session)
        await owner.client.send(BriefingSharingSet(mode=BriefingSharing.TEAM))
        await owner.next(BriefingSharingChanged)
        cleo = await session.guest("Cleo", Role.VIEWER)
        await cleo.client.send(BriefingRequest())
        delivered = await cleo.next(BriefingDelivered)
        assert delivered.text == ""
        assert delivered.error is not None
        assert delivered.error.startswith("the model could not write it")


async def test_notes_given_to_an_agent_reach_its_next_prompt_once(tmp_path: Path) -> None:
    provider = FakeProvider([reply("read it"), reply("and again")])
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        guest = await session.guest("Alia", Role.PARTICIPANT)
        await owner.client.send(
            BriefingImport(source="bek", as_of_seq=7, text="Goal: fix login. Done: a retry.")
        )
        imported = await owner.next(BriefingImported)
        assert (imported.item.source, imported.item.as_of_seq) == ("bek", 7)
        await guest.next(BriefingImported)
        assert [item.source for item in owner.client.projection.state.briefings_imported] == ["bek"]

        await owner.client.send(PromptSubmit(text="continue his work"))
        await owner.next(RunEnded)
        sent = [message.content for message in provider.requests[0].messages]
        assert sent[0].startswith(NOTES_HEADER.format(source="bek"))
        assert sent[0].endswith("Goal: fix login. Done: a retry.")

        await owner.client.send(PromptSubmit(text="and now?"))
        await owner.next(RunEnded)
        again = [message.content for message in provider.requests[1].messages]
        assert sum(NOTES_HEADER.format(source="bek") in content for content in again) == 1

        duplicate = BriefingImport(source="bek", as_of_seq=7, text="same")
        assert await rejected(owner.client.send(duplicate)) is ErrorCode.CONFLICT
        assert await rejected(guest.client.send(duplicate)) is ErrorCode.FORBIDDEN


async def test_after_notes_even_a_host_prompt_in_auto_mode_asks_before_it_writes(
    tmp_path: Path,
) -> None:
    async def attempt(import_first: bool, sub: str) -> bool:
        (tmp_path / sub).mkdir()
        provider = FakeProvider(
            [use_tool("write", "c1", path="made.txt", content="x"), reply("ok")]
        )
        async with running_session(tmp_path / sub, relayed=False, provider=provider) as session:
            owner = await session.owner()
            await owner.client.send(PermissionModeSet(mode=PermissionMode.AUTO))
            await owner.next(PermissionModeChanged)
            if import_first:
                await owner.client.send(BriefingImport(source="bek", text="notes"))
                await owner.next(BriefingImported)
            await owner.client.send(PromptSubmit(text="make it"))
            for _ in range(200):
                if any(isinstance(event, ApprovalRequested) for event in owner.events):
                    return True
                if any(isinstance(event, RunEnded) for event in owner.events):
                    return False
                await asyncio.sleep(0.05)
            raise AssertionError("neither an approval nor the end of the run")

    assert not await attempt(False, "plain")
    assert await attempt(True, "with-notes")


async def test_the_notes_and_the_caution_survive_a_restart(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()

    def settings() -> HostSettings:
        return HostSettings(
            workspace=workspace,
            data_dir=tmp_path / "data",
            room="r_again",
            port=free_port(),
            provider="fake",
            approval_timeout_s=30,
        )

    first = await build_host(settings(), provider=FakeProvider([]))
    serving = asyncio.create_task(first.serve())
    owner = Watcher(SessionClient(JoinLink.parse(first.host_link), name="host", client=CLIENT))
    await owner.next(SessionSnapshot)
    await owner.client.send(BriefingImport(source="bek", as_of_seq=3, text="Goal: fix login."))
    await owner.next(BriefingImported)
    await owner.stop()
    serving.cancel()
    await asyncio.gather(serving, return_exceptions=True)
    await first.close()

    provider = FakeProvider([use_tool("write", "c1", path="made.txt", content="x"), reply("ok")])
    second = await build_host(settings(), provider=provider)
    serving = asyncio.create_task(second.serve())
    again = Watcher(SessionClient(JoinLink.parse(second.host_link), name="host", client=CLIENT))
    try:
        await again.next(SessionSnapshot)
        assert [item.source for item in again.client.projection.state.briefings_imported] == ["bek"]
        await again.client.send(PermissionModeSet(mode=PermissionMode.AUTO))
        await again.next(PermissionModeChanged)
        await again.client.send(PromptSubmit(text="make it"))
        await again.next(ApprovalRequested)
        sent = [message.content for message in provider.requests[0].messages]
        assert sent[0].startswith(NOTES_HEADER.format(source="bek"))
    finally:
        await again.stop()
        serving.cancel()
        await asyncio.gather(serving, return_exceptions=True)
        await second.close()
