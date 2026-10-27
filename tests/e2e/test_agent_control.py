import asyncio
import json
from pathlib import Path

from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.host.config import HostSettings
from plural.host.control import Control
from plural.protocol.commands import ApprovalRespond, PromptSubmit
from plural.protocol.events import (
    AgentChanged,
    ApprovalRequested,
    RunEnded,
    SessionWelcome,
    ToolEnded,
)
from plural.protocol.models import ApprovalDecision
from tests.e2e.support import Session, running_session

SECRET = "gsk_Zq9vLw3pT7xN2mB8kR4yH6cD1fJ5sG0aE"


def request(kind: str, **config: object) -> str:
    return json.dumps({"id": "q1", "type": kind, "config": config})


class Replies:
    def __init__(self) -> None:
        self.items: list[dict[str, object]] = []

    def __call__(self, message: dict[str, object]) -> None:
        self.items.append(message)

    async def next(self) -> dict[str, object]:
        for _ in range(500):
            if self.items:
                return self.items.pop(0)
            await asyncio.sleep(0.01)
        raise AssertionError("no reply")


async def test_the_new_agent_is_announced_to_everyone_and_used_for_the_next_run(
    tmp_path: Path,
) -> None:
    original = FakeProvider([reply("from the original agent")])
    async with running_session(tmp_path, relayed=False, provider=original) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        assert owner.client.projection.state.agent == "demo agent (scripted)"

        replies = Replies()
        control = Control(session.host, HostSettings(provider="fake"), replies)
        await control.handle(request("configure", provider="fake"))
        outcome = await replies.next()
        assert outcome == {
            "type": "result",
            "id": "q1",
            "ok": True,
            "agent": "demo agent (scripted)",
        }

        await control.handle(
            request(
                "configure",
                provider="openai",
                provider_name="Cerebras",
                model="qwen3:4b",
                base_url="http://127.0.0.1:1/v1",
            )
        )
        assert (await replies.next())["agent"] == "Cerebras · qwen3:4b"
        changed = await guest.next(AgentChanged)
        assert changed.agent == "Cerebras · qwen3:4b"
        assert guest.client.projection.state.agent == "Cerebras · qwen3:4b"

        await control.handle(request("configure", provider="fake"))
        await replies.next()
        await owner.client.send(PromptSubmit(text="hello"))
        ended = await owner.next(ToolEnded)
        assert "notes.txt" in ended.output


async def test_a_busy_agent_is_not_swapped(tmp_path: Path) -> None:
    provider = FakeProvider([use_tool("bash", "c1", command="echo hello"), reply("done")])
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        await owner.client.send(PromptSubmit(text="go"))
        approval = (await owner.next(ApprovalRequested)).approval

        replies = Replies()
        control = Control(session.host, HostSettings(provider="fake"), replies)
        await control.handle(request("configure", provider="fake"))
        busy = await replies.next()
        assert busy["ok"] is False
        assert "busy" in str(busy["error"])

        await owner.client.send(
            ApprovalRespond(approval_id=approval.id, decision=ApprovalDecision.ONCE)
        )
        await owner.next(RunEnded)
        await control.handle(request("configure", provider="fake"))
        assert (await replies.next())["ok"] is True


async def test_a_key_given_later_is_masked_in_what_everyone_sees(tmp_path: Path) -> None:
    provider = FakeProvider([reply("ok")])
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        replies = Replies()
        control = Control(session.host, HostSettings(provider="fake"), replies)
        await control.handle(request("configure", provider="fake", api_key=SECRET))
        assert (await replies.next())["ok"] is True

        await owner.client.send(PromptSubmit(text=f"$ echo {SECRET}"))
        approval = (await owner.next(ApprovalRequested)).approval
        await owner.client.send(
            ApprovalRespond(approval_id=approval.id, decision=ApprovalDecision.ONCE)
        )
        ended = await guest.next(ToolEnded)
        assert SECRET not in ended.output
        assert SECRET not in json.dumps([e.model_dump(mode="json") for e in guest.events])


async def test_a_new_joiner_is_told_the_current_agent(session: Session) -> None:
    replies = Replies()
    control = Control(session.host, HostSettings(provider="fake"), replies)
    await control.handle(
        request("configure", provider="openai", model="qwen3:4b", base_url="http://127.0.0.1:1/v1")
    )
    await replies.next()
    late = await session.guest("Cleo")
    welcome = next(e for e in late.events if isinstance(e, SessionWelcome))
    assert welcome.agent == "openai · qwen3:4b · local"
    assert late.client.projection.state.agent == "openai · qwen3:4b · local"


async def test_testing_a_config_reports_without_changing_the_agent(tmp_path: Path) -> None:
    async with running_session(
        tmp_path, relayed=False, provider=FakeProvider([reply("ok")])
    ) as session:
        replies = Replies()
        control = Control(session.host, HostSettings(provider="fake"), replies)
        await control.handle(request("test", provider="fake"))
        result = await replies.next()
        assert result["ok"] is True
        assert str(result["message"]).startswith("answered in ")

        await control.handle(request("test", provider="anthropic"))
        failure = await replies.next()
        assert failure["ok"] is False
        assert "ANTHROPIC_API_KEY" in str(failure["error"])
        assert session.host.actor.state.agent == "demo agent (scripted)"


async def test_garbage_is_ignored_without_echoing_it(tmp_path: Path) -> None:
    async with running_session(
        tmp_path, relayed=False, provider=FakeProvider([reply("ok")])
    ) as session:
        replies = Replies()
        control = Control(session.host, HostSettings(provider="fake"), replies)
        for line in (
            "",
            "not json",
            "[]",
            '{"id": "x"}',
            "x" * 70_000,
            f'{{"api_key": "{SECRET}"}}',
        ):
            await control.handle(line)
        await asyncio.sleep(0.05)
        assert replies.items == []
