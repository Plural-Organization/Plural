import asyncio
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Final

from pydantic import Field, JsonValue

from plural.agent.agents import AgentLibrary, AgentSpec
from plural.agent.context import ContextBuilder, Environment
from plural.agent.events import MessageEnd, RunEnd, ToolEnd, ToolStart
from plural.agent.gate import GateResult, PolicyGate
from plural.agent.loop import AgentLoop
from plural.agent.messages import UserTurn
from plural.agent.providers.base import ToolSchema
from plural.agent.tools.base import PreparedCall, ToolArgs, ToolCtx, ToolError, ToolResult
from plural.agent.tools.registry import ToolRegistry
from plural.agent.tools.truncation import truncate_head
from plural.core.ports import IdGenerator
from plural.core.provenance import direct
from plural.protocol.models import (
    Actor,
    ActorKind,
    Provenance,
    Role,
    RunEndReason,
    ToolCallView,
    ToolRisk,
    Usage,
)

AGENT_TOOL: Final = "agent"
MAX_TASK: Final = 8000


class AgentArgs(ToolArgs):
    agent: str = Field(description="Name of the sub-agent.")
    task: str = Field(
        min_length=1,
        max_length=MAX_TASK,
        description="The complete task, with everything the sub-agent needs to know.",
    )


class _SharedGate:
    """The parent's gate, without resetting the parent's rejection memory per sub-run."""

    def __init__(self, gate: PolicyGate) -> None:
        self._gate = gate

    def begin_run(self) -> None:
        return None

    async def check(
        self, call: ToolCallView, *, subject: str, provenance: Provenance
    ) -> GateResult:
        return await self._gate.check(call, subject=subject, provenance=provenance)

    def turn_limit(self, *, usage: Usage, provenance: Provenance) -> str | None:
        return self._gate.turn_limit(usage=usage, provenance=provenance)


class AgentTool:
    """Hands a task to a sub-agent loop and returns its report."""

    def __init__(
        self,
        *,
        library: AgentLibrary,
        tools: ToolRegistry,
        gate: PolicyGate,
        environment: Environment | None,
        ids: IdGenerator,
    ) -> None:
        self._library = library
        self._tools = tools
        self._gate = _SharedGate(gate)
        self._environment = environment
        self._ids = ids
        self._parent: Callable[[], AgentLoop] | None = None

    def attach(self, parent: Callable[[], AgentLoop]) -> None:
        self._parent = parent

    @property
    def name(self) -> str:
        return AGENT_TOOL

    def schema(self) -> ToolSchema:
        names = [agent.name for agent in self._library.agents]
        parameters = AgentArgs.model_json_schema()
        parameters["properties"]["agent"]["enum"] = names
        return ToolSchema(
            name=AGENT_TOOL,
            description="Hand a self-contained task to a sub-agent and get its report back.",
            parameters=parameters,
        )

    def prepare(self, raw: Mapping[str, JsonValue]) -> PreparedCall:
        args = AgentArgs.model_validate(raw)
        spec = self._library.get(args.agent)
        if spec is None:
            known = ", ".join(agent.name for agent in self._library.agents)
            raise ToolError(f"no sub-agent named {args.agent}; have: {known}")
        risk = ToolRisk.READ if spec.read_only else ToolRisk.EXEC
        return PreparedCall(
            name=AGENT_TOOL,
            risk=risk,
            subject=f"{spec.name}: {' '.join(args.task.split())[:120]}",
            execute=lambda ctx: self.run(spec, args.task, ctx),
        )

    async def run(self, spec: AgentSpec, task: str, ctx: ToolCtx) -> ToolResult:
        if self._parent is None:
            raise ToolError("sub-agents are not available on this host")
        parent = self._parent()
        provider = parent.helper if spec.role == "fast" and parent.helper else parent.provider
        model = "fast" if provider is parent.helper else "main"
        child = AgentLoop(
            provider=provider,
            tools=self._tools.subset(tool for tool in spec.tools if tool != AGENT_TOOL),
            gate=self._gate,
            context=ContextBuilder(system_prompt=spec.prompt, environment=self._environment),
            tool_ctx=replace(ctx, emit=_quiet),
            ids=self._ids,
            limits=replace(parent.limits, max_turns=spec.max_turns),
        )
        provenance = ctx.provenance or direct("p_host", Role.HOST)
        turn = UserTurn(
            id=self._ids.new("pm_"),
            author=Actor(id=provenance.initiator_id, kind=ActorKind.AGENT, name="main agent"),
            provenance=provenance,
            text=task,
        )
        ctx.emit(f"{spec.name} on the {model} model\n")
        report = ""
        calls = 0
        ending: RunEnd | None = None
        async for event in child.run(turn, cancel=ctx.cancel or asyncio.Event()):
            match event:
                case ToolStart(call=call):
                    calls += 1
                    ctx.emit(f"· {call.name} {call.subject}\n")
                case ToolEnd(result=result) if result.is_error:
                    ctx.emit(f"  ✗ {_first_line(result.content)}\n")
                case MessageEnd(text=text) if text.strip():
                    report = text.strip()
                case RunEnd() as end:
                    ending = end
                case _:
                    pass
        usage = child.usage
        parent.spend(model, spec.name, usage, uses=1)
        tokens = usage.prompt_tokens + usage.output_tokens
        footer = f"\n\n[{spec.name} · {model} model · {calls} tool calls · {tokens} tokens]"
        if ending is not None and ending.reason is RunEndReason.ABORTED:
            raise ToolError("the sub-agent was stopped")
        if not report:
            reason = ending.error if ending and ending.error else "it produced no report"
            raise ToolError(f"{spec.name} did not finish: {reason}")
        unfinished = ending is not None and ending.reason is not RunEndReason.STOP
        note = f"\n\n(unfinished: {ending.error or ending.reason})" if unfinished and ending else ""
        return ToolResult(truncate_head(report + note) + footer)


def _quiet(_chunk: str) -> None:
    return None


def _first_line(text: str) -> str:
    return text.splitlines()[0][:120] if text.strip() else "failed"
