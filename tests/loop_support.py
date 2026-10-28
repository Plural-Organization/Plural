import asyncio
from pathlib import Path

from plural.agent.context import ContextBuilder
from plural.agent.events import AgentEvent
from plural.agent.gate import GateResult
from plural.agent.loop import AgentLoop, LoopLimits
from plural.agent.messages import UserTurn
from plural.agent.providers.base import LLMProvider
from plural.agent.sandbox.base import Workspace
from plural.agent.sandbox.local import LocalBackend
from plural.agent.tools.base import ToolCtx
from plural.agent.tools.registry import builtin_tools
from plural.core.provenance import direct, from_proposal
from plural.host.system import UlidGenerator
from plural.protocol.models import Actor, ActorKind, Provenance, Role, ToolCallView


class StubGate:
    def __init__(self, *, allowed: bool = True, block: bool = False) -> None:
        self.allowed = allowed
        self.block = block
        self.runs = 0
        self.seen: list[tuple[str, Provenance]] = []

    def begin_run(self) -> None:
        self.runs += 1

    async def check(
        self, call: ToolCallView, *, subject: str, provenance: Provenance
    ) -> GateResult:
        self.seen.append((subject, provenance))
        if self.block:
            await asyncio.Event().wait()
        return GateResult(allowed=self.allowed, reason="stub")


def turn(text: str, *, guest: bool = False) -> UserTurn:
    provenance = from_proposal("p_alia", Role.PARTICIPANT) if guest else direct("p_host", Role.HOST)
    name = "Alia" if guest else "Host"
    actor = Actor(id=provenance.initiator_id, kind=ActorKind.HUMAN, name=name)
    return UserTurn(id=f"pm_{text}", author=actor, provenance=provenance, text=text)


def make_loop(
    tmp_path: Path,
    provider: LLMProvider,
    gate: StubGate,
    limits: LoopLimits | None = None,
    helper: LLMProvider | None = None,
) -> AgentLoop:
    (tmp_path / "a.txt").write_text("alpha\n")
    return AgentLoop(
        provider=provider,
        tools=builtin_tools(),
        gate=gate,
        context=ContextBuilder(),
        tool_ctx=ToolCtx(workspace=Workspace.at(tmp_path), backend=LocalBackend()),
        ids=UlidGenerator(),
        limits=limits,
        helper=helper,
    )


async def collect(loop: AgentLoop, prompt: UserTurn) -> list[AgentEvent]:
    return [event async for event in loop.run(prompt, cancel=asyncio.Event())]
