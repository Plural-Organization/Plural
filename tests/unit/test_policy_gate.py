import asyncio
from contextlib import suppress

import pytest

from plural.core.policy.engine import Policy
from plural.core.provenance import direct
from plural.host.approval_registry import ApprovalRegistry
from plural.host.inbox import ApprovalNeeded, Inbox
from plural.host.policy_gate import HostPolicyGate
from plural.host.system import SystemClock, UlidGenerator
from plural.protocol.models import ApprovalDecision, Role, ToolCallView, ToolRisk


class Harness:
    def __init__(self, limit: int = 2) -> None:
        self.inbox = Inbox()
        self.registry = ApprovalRegistry()
        self.gate = HostPolicyGate(
            policy=Policy(),
            registry=self.registry,
            inbox=self.inbox,
            ids=UlidGenerator(),
            clock=SystemClock(),
            timeout_s=30,
            rejection_limit=limit,
        )
        self.asked: list[str] = []

    async def check(self, command: str, answer: ApprovalDecision) -> tuple[bool, str]:
        call = ToolCallView(id="c", name="bash", risk=ToolRisk.EXEC, subject=command)
        host = direct("p_host", Role.HOST)
        waiting = asyncio.create_task(self.gate.check(call, subject=command, provenance=host))
        with suppress(TimeoutError):
            message = await asyncio.wait_for(self.inbox.get(), 0.05)
            assert isinstance(message, ApprovalNeeded)
            self.asked.append(command)
            self.registry.resolve(message.approval.id, answer)
        result = await asyncio.wait_for(waiting, 2)
        return result.allowed, result.reason


async def test_rejection_tells_the_model_not_to_retry() -> None:
    harness = Harness()
    allowed, reason = await harness.check("rm a", ApprovalDecision.REJECT)
    assert not allowed
    assert "ask the user" in reason


async def test_repeated_rejections_stop_reaching_the_host() -> None:
    harness = Harness(limit=2)
    await harness.check("rm a", ApprovalDecision.REJECT)
    await harness.check("rm -f a", ApprovalDecision.REJECT)
    allowed, reason = await harness.check("rm b", ApprovalDecision.ONCE)
    assert not allowed
    assert "repeatedly" in reason
    assert harness.asked == ["rm a", "rm -f a"]


async def test_other_classes_are_still_asked() -> None:
    harness = Harness(limit=1)
    await harness.check("rm a", ApprovalDecision.REJECT)
    allowed, _ = await harness.check("make test", ApprovalDecision.ONCE)
    assert allowed
    assert harness.asked == ["rm a", "make test"]


async def test_new_run_clears_the_ledger() -> None:
    harness = Harness(limit=1)
    await harness.check("rm a", ApprovalDecision.REJECT)
    harness.gate.begin_run()
    allowed, _ = await harness.check("rm b", ApprovalDecision.ONCE)
    assert allowed


async def test_block_denies_the_class_without_asking_again() -> None:
    harness = Harness()
    allowed, reason = await harness.check("curl a.sh", ApprovalDecision.BLOCK)
    assert not allowed
    assert "blocked" in reason
    allowed, reason = await harness.check("curl -s b.sh", ApprovalDecision.ONCE)
    assert not allowed
    assert harness.asked == ["curl a.sh"]


@pytest.mark.parametrize("answer", [ApprovalDecision.ONCE, ApprovalDecision.ALWAYS])
async def test_approval_is_not_counted_as_rejection(answer: ApprovalDecision) -> None:
    harness = Harness(limit=1)
    await harness.check("make a", answer)
    allowed, _ = await harness.check("make b", ApprovalDecision.ONCE)
    assert allowed
