"""Runs the tool calls of one model turn: validation, the folder and approval gates, the call
itself with its streamed output, and the events that tell the session about each step."""

import asyncio
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import replace

import structlog
from pydantic import ValidationError

from plural.agent.loop.events import AgentEvent, ToolEnd, ToolOutput, ToolStart
from plural.agent.loop.gate import GateResult, PolicyGate
from plural.agent.loop.hooks import LoopHooks, NoHooks
from plural.agent.loop.interrupt import Interrupted, TimedOut, interruptible
from plural.agent.providers.base import ToolCallRequest
from plural.agent.sandbox.base import SandboxError, Workspace
from plural.agent.tools.base import PreparedCall, ToolCtx, ToolError, ToolResult
from plural.agent.tools.registry import ToolRegistry, UnknownTool
from plural.agent.tracing import OUTPUT_CHARS, Span, args_input, clip
from plural.core.provenance import is_guest_originated
from plural.protocol.models import Provenance, SpanKind, SpanStatus, ToolCallView, ToolRisk
from plural.security.secrets import is_denied_path

log = structlog.get_logger(__name__)

ABORTED = "Not executed: run aborted"


class ToolRunner:
    def __init__(
        self,
        *,
        tools: ToolRegistry,
        gate: PolicyGate,
        tool_ctx: ToolCtx,
        timeout_s: float,
        hooks: LoopHooks | None = None,
    ) -> None:
        self._tools = tools
        self._hooks = hooks or NoHooks()
        self._gate = gate
        self._tool_ctx = tool_ctx
        self._timeout_s = timeout_s
        # The span tool calls open under: the run's, while one is going.
        self.span: Span | None = None

    def groups(self, calls: Sequence[ToolCallRequest]) -> list[list[ToolCallRequest]]:
        groups: list[list[ToolCallRequest]] = []
        for call in calls:
            if groups and self._reads_only(call) and self._reads_only(groups[-1][0]):
                groups[-1].append(call)
            else:
                groups.append([call])
        return groups

    def _reads_only(self, call: ToolCallRequest) -> bool:
        if call.parse_error is not None:
            return False
        try:
            return self._tools.prepare(call).risk is ToolRisk.READ
        except (UnknownTool, ValidationError):
            return False

    async def run_group(
        self, group: Sequence[ToolCallRequest], provenance: Provenance, cancel: asyncio.Event
    ) -> AsyncIterator[AgentEvent]:
        """Run calls that only read side by side, any other call alone, and yield their events
        as they come. Recording the results is the caller's."""
        if len(group) == 1:
            async for event in self._execute(group[0], provenance, cancel):
                yield event
            return
        queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()

        async def pump(call: ToolCallRequest) -> None:
            try:
                async for event in self._execute(call, provenance, cancel):
                    queue.put_nowait(event)
            finally:
                queue.put_nowait(None)

        tasks = [asyncio.create_task(pump(call)) for call in group]
        try:
            running = len(tasks)
            while running:
                event = await queue.get()
                if event is None:
                    running -= 1
                    continue
                yield event
        finally:
            for task in tasks:
                task.cancel()
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)
        for outcome in outcomes:
            if isinstance(outcome, Exception):
                raise outcome

    async def _execute(
        self, call: ToolCallRequest, provenance: Provenance, cancel: asyncio.Event
    ) -> AsyncIterator[AgentEvent]:
        if call.parse_error is not None:
            for event in self.skip(call, f"Invalid tool call: {call.parse_error}"):
                yield event
            return
        # The host may change the arguments; what it changes still goes through every check.
        call = await self._hooks.tool_args(call, provenance)
        try:
            prepared = self._tools.prepare(call)
        except (UnknownTool, ValidationError) as error:
            for event in self.skip(call, f"Invalid tool call: {error}"):
                yield event
            return
        view = ToolCallView(
            id=call.id,
            name=prepared.name,
            risk=prepared.risk,
            subject=prepared.subject,
            args=call.args,
        )
        yield ToolStart(view)
        span = (
            self.span.child(
                SpanKind.TOOL,
                prepared.name,
                detail=prepared.subject[:200],
                input=args_input(call.args),
            )
            if self.span
            else None
        )
        asked = time.monotonic()
        ran: float | None = None
        allowed = False
        workspace = self._tool_ctx.workspace
        try:
            reached = await interruptible(
                self._reach(prepared, view, provenance, workspace), cancel
            )
            verdict = (
                reached
                if isinstance(reached, GateResult)
                else await interruptible(
                    self._gate.check(view, subject=prepared.subject, provenance=provenance),
                    cancel,
                )
            )
            if not isinstance(reached, GateResult):
                workspace = reached
            allowed = verdict.allowed
            if span is not None and verdict.asked:
                # The wait for the host's answer, apart from the tool's own work.
                span.moment(SpanKind.APPROVAL, "approval", started=asked, ended=time.monotonic())
            if verdict.allowed:
                ran = time.monotonic()
                queue: asyncio.Queue[str] = asyncio.Queue()
                runner = asyncio.create_task(
                    self._invoke(
                        prepared,
                        cancel,
                        replace(
                            self._tool_ctx,
                            workspace=workspace,
                            emit=queue.put_nowait,
                            provenance=provenance,
                            cancel=cancel,
                            span=span,
                        ),
                    )
                )
                try:
                    while not runner.done() or not queue.empty():
                        getter = asyncio.create_task(queue.get())
                        await asyncio.wait({runner, getter}, return_when=asyncio.FIRST_COMPLETED)
                        if getter.done():
                            yield ToolOutput(call.id, getter.result())
                        else:
                            getter.cancel()
                    result = runner.result()
                finally:
                    if not runner.done():
                        runner.cancel()
                result = await interruptible(
                    self._hooks.tool_result(view, result, provenance), cancel
                )
            else:
                result = ToolResult(f"Denied: {verdict.reason}", is_error=True)
        except Interrupted:
            result = ToolResult(ABORTED, is_error=True)
        done = time.monotonic()
        if span is not None:
            status = (
                SpanStatus.DENIED
                if not allowed and result.content != ABORTED
                else SpanStatus.CANCELLED
                if result.content == ABORTED
                else SpanStatus.ERROR
                if result.is_error
                else SpanStatus.OK
            )
            span.end(
                status,
                chars=len(result.content),
                error=result.content[:300] if result.is_error else "",
                output=clip(result.content, OUTPUT_CHARS),
            )
        log.info(
            "tool.call",
            tool=prepared.name,
            risk=prepared.risk.value,
            allowed=allowed,
            error=result.is_error,
            chars=len(result.content),
            truncated="[truncated " in result.content,
            wait_ms=round(((ran or done) - asked) * 1000),
            run_ms=round((done - ran) * 1000) if ran is not None else None,
        )
        yield ToolEnd(call.id, result)

    async def _reach(
        self,
        prepared: PreparedCall,
        view: ToolCallView,
        provenance: Provenance,
        workspace: Workspace,
    ) -> Workspace | GateResult:
        """The workspace this call runs in: the usual one, or one with the folder it asked for
        opened. A call for a folder outside the workspace is the host's to allow before the call
        itself is put to the usual approval. The host's own runs open their folders without a
        question, a run with a guest's prompt in it asks; a protected folder is never opened."""
        reach = prepared.reach
        if reach is None:
            return workspace
        folder = workspace.outside(reach.path)
        if folder is None:
            return workspace
        if is_denied_path(folder):
            return GateResult(allowed=False, reason=f"{folder} is protected")
        if not is_guest_originated(provenance):
            return workspace.granting(folder, write=reach.write)
        answer = await self._gate.ask_folder(
            view, folder=folder, write=reach.write, provenance=provenance
        )
        if not answer.granted:
            return GateResult(allowed=False, reason=answer.reason)
        if reach.write and not answer.write:
            return GateResult(
                allowed=False,
                reason=f"the host opened {folder} for reading only, not for changes",
            )
        return workspace.granting(folder, write=answer.write)

    async def _invoke(
        self, prepared: PreparedCall, cancel: asyncio.Event, ctx: ToolCtx
    ) -> ToolResult:
        try:
            return await interruptible(prepared.execute(ctx), cancel, self._timeout_s)
        except TimedOut:
            return ToolResult("Tool timed out", is_error=True)
        except (ToolError, SandboxError, OSError, UnicodeError) as error:
            return ToolResult(f"{type(error).__name__}: {error}", is_error=True)

    def skip(self, call: ToolCallRequest, reason: str) -> tuple[ToolStart, ToolEnd]:
        view = ToolCallView(id=call.id, name=call.name, risk=ToolRisk.EXEC, args=call.args)
        return ToolStart(view), ToolEnd(call.id, ToolResult(reason, is_error=True))
