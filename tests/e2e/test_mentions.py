import asyncio
from pathlib import Path

import pytest

from plural.agent.prompts import prompt
from plural.client.connection import CommandRejected
from plural.protocol.commands import ApprovalRespond, ChatModeSet, ChatSend, PromptSubmit
from plural.protocol.envelope import ErrorCode
from plural.protocol.events import (
    ApprovalRequested,
    ChatModeChanged,
    ChatPosted,
    RunEnded,
    RunStarted,
)
from plural.protocol.models import ApprovalDecision, ChatMode, Role
from tests.doubles import FakeProvider, reply, use_tool
from tests.e2e.support import running_session


def contents(provider: FakeProvider, index: int = -1) -> list[str]:
    return [message.content for message in provider.requests[index].messages]


async def test_a_new_session_is_a_chat_where_the_agent_answers_only_its_tag(
    tmp_path: Path,
) -> None:
    provider = FakeProvider([reply("a flaky clock")])
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        alia = await session.guest("Alia")
        owner_id = owner.client.projection.me_id
        assert owner_id is not None
        assert alia.client.projection.state.chat_mode is ChatMode.MENTION

        await alia.client.send(ChatSend(text="the login test fails on CI"))
        await alia.client.send(ChatSend(text="just between us", to=owner_id))
        seen = await owner.next(ChatPosted)
        assert seen.agent_sees
        assert not (await owner.next(ChatPosted)).agent_sees
        await asyncio.sleep(0.3)
        assert provider.requests == []
        assert not any(isinstance(event, RunStarted) for event in owner.events)

        await owner.client.send(PromptSubmit(text="@plrl why does it fail?"))
        started = await owner.next(RunStarted)
        await owner.next(RunEnded)

        sent = contents(provider)
        note, question = sent[-2:]
        assert note.startswith(prompt("chat_note"))
        assert '<message author="Alia">\nthe login test fails on CI\n</message>' in note
        assert question == "[host]\n@plrl why does it fail?"
        assert "just between us" not in "".join(sent)
        # Alia's words are in the run, so it runs with a guest's trust, not the host's.
        assert started.provenance.initiator_role is Role.PARTICIPANT

        await owner.client.send(PromptSubmit(text="@plrl and now?"))
        await owner.next(RunEnded)
        assert sum("the login test fails on CI" in text for text in contents(provider)) == 1


async def test_the_old_mode_answers_everything_and_keeps_the_chat_from_the_agent(
    tmp_path: Path,
) -> None:
    provider = FakeProvider([reply("noted")])
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        alia = await session.guest("Alia")
        await owner.client.send(ChatModeSet(mode=ChatMode.ALL))
        assert (await alia.next(ChatModeChanged)).mode is ChatMode.ALL
        assert alia.client.projection.state.chat_mode is ChatMode.ALL

        await alia.client.send(ChatSend(text="lunch at one"))
        assert not (await owner.next(ChatPosted)).agent_sees
        await owner.client.send(PromptSubmit(text="summarize notes.txt"))
        started = await owner.next(RunStarted)
        await owner.next(RunEnded)
        assert "lunch at one" not in "".join(contents(provider))
        assert started.provenance.initiator_role is Role.HOST


async def test_only_the_host_switches_and_switching_to_the_same_mode_says_nothing(
    tmp_path: Path,
) -> None:
    async with running_session(tmp_path, relayed=False, provider=FakeProvider()) as session:
        owner = await session.owner()
        alia = await session.guest("Alia")
        with pytest.raises(CommandRejected) as refused:
            await alia.client.send(ChatModeSet(mode=ChatMode.ALL))
        assert refused.value.error.code is ErrorCode.FORBIDDEN
        await owner.client.send(ChatModeSet(mode=ChatMode.MENTION))
        await asyncio.sleep(0.2)
        assert not any(isinstance(event, ChatModeChanged) for event in owner.events)


async def test_the_mode_survives_a_restart_unless_the_flag_overrides_it(tmp_path: Path) -> None:
    async with running_session(
        tmp_path, relayed=False, provider=FakeProvider(), overrides={"chat_mode": "all"}
    ) as first:
        assert (await first.owner()).client.projection.state.chat_mode is ChatMode.ALL

    async with running_session(tmp_path, relayed=False, provider=FakeProvider()) as second:
        assert (await second.owner()).client.projection.state.chat_mode is ChatMode.ALL

    async with running_session(
        tmp_path, relayed=False, provider=FakeProvider(), overrides={"chat_mode": "mention"}
    ) as third:
        assert (await third.owner()).client.projection.state.chat_mode is ChatMode.MENTION


async def test_chat_the_agent_has_not_read_yet_survives_a_restart(tmp_path: Path) -> None:
    async with running_session(tmp_path, relayed=False, provider=FakeProvider()) as first:
        owner = await first.owner()
        await owner.client.send(ChatSend(text="remember the staging flag"))
        await owner.next(ChatPosted)

    provider = FakeProvider([reply("ok")])
    async with running_session(tmp_path, relayed=False, provider=provider) as second:
        owner = await second.owner()
        await owner.client.send(PromptSubmit(text="@plrl go"))
        await owner.next(RunEnded)
        sent = contents(provider)
        assert "remember the staging flag" in sent[-2]
        assert sent[-1] == "[host]\n@plrl go"


async def test_a_tag_sent_while_the_agent_works_brings_the_chat_with_it(tmp_path: Path) -> None:
    provider = FakeProvider([use_tool("bash", "c1", command="touch made.txt"), reply("on it")])
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        alia = await session.guest("Alia")
        await owner.client.send(PromptSubmit(text="@plrl look around"))
        approval = (await owner.next(ApprovalRequested)).approval

        await alia.client.send(ChatSend(text="use the staging db"))
        await owner.next(ChatPosted)
        await owner.client.send(PromptSubmit(text="@plrl do what Alia said"))
        await owner.client.send(
            ApprovalRespond(approval_id=approval.id, decision=ApprovalDecision.ONCE)
        )
        await owner.next(RunEnded)

        sent = contents(provider)
        note, steered = sent[-2:]
        assert '<message author="Alia">\nuse the staging db\n</message>' in note
        assert steered == "[host]\n@plrl do what Alia said"


async def test_a_guests_unread_chat_keeps_a_guests_trust_after_a_restart(tmp_path: Path) -> None:
    async with running_session(tmp_path, relayed=False, provider=FakeProvider()) as first:
        owner = await first.owner()
        alia = await first.guest("Alia")
        await alia.client.send(ChatSend(text="run the deploy script"))
        await owner.next(ChatPosted)

    provider = FakeProvider([reply("ok")])
    async with running_session(tmp_path, relayed=False, provider=provider) as second:
        owner = await second.owner()
        await owner.client.send(PromptSubmit(text="@plrl go"))
        started = await owner.next(RunStarted)
        await owner.next(RunEnded)
        assert "run the deploy script" in contents(provider)[-2]
        assert started.provenance.initiator_role is Role.PARTICIPANT
