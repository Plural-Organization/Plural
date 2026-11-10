from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from typing import Final

from plural.agent.loop.gate import FolderResult, GateResult
from plural.core.policy.engine import PLAN_MODE, Policy, ToolInvocation, evaluate, run_limit
from plural.core.policy.rejections import RejectionLedger
from plural.core.policy.rules import RuleSet
from plural.core.ports import Clock, IdGenerator
from plural.host.approval_registry import ApprovalRegistry
from plural.host.inbox import ApprovalNeeded, Inbox
from plural.host.plugins import Verdict
from plural.protocol.models import (
    ApprovalDecision,
    ApprovalView,
    FolderAccess,
    PermissionMode,
    PolicyAction,
    Provenance,
    ToolCallView,
    Usage,
)
from plural.security.secrets import is_denied_path

FINAL: Final = "Do not retry this or an equivalent action; ask the user how to proceed instead"

# Plugin tool_call hooks: they may ask for an approval or refuse, never allow.
Guard = Callable[[ToolCallView, Provenance], Awaitable[Verdict | None]]


class HostPolicyGate:
    def __init__(
        self,
        *,
        policy: Policy,
        registry: ApprovalRegistry,
        inbox: Inbox,
        ids: IdGenerator,
        clock: Clock,
        timeout_s: float,
        rejection_limit: int,
        guard: Guard | None = None,
    ) -> None:
        self._policy = policy
        self._guard = guard
        self._registry = registry
        self._inbox = inbox
        self._ids = ids
        self._clock = clock
        self._timeout = timedelta(seconds=timeout_s)
        self._rejections = RejectionLedger(rejection_limit)

    @property
    def policy(self) -> Policy:
        return self._policy

    def use_session_rules(self, rules: RuleSet) -> None:
        self._policy = self._policy.with_session(rules)

    def use_mode(self, mode: PermissionMode) -> None:
        self._policy = self._policy.with_mode(mode)

    def begin_run(self) -> None:
        self._rejections.reset()

    def turn_limit(self, *, usage: Usage, provenance: Provenance) -> str | None:
        return run_limit(self._policy, usage, provenance)

    async def ask_folder(
        self, call: ToolCallView, *, folder: Path, write: bool, provenance: Provenance
    ) -> FolderResult:
        """Put a folder outside the workspace to the host. It is asked every time, whoever asks:
        nothing is remembered, and a protected folder is never offered."""
        if is_denied_path(folder):
            return FolderResult(False, False, f"{folder} is protected. {FINAL}")
        approval = ApprovalView(
            id=self._ids.new("ap_"),
            call=call,
            provenance=provenance,
            timeout_at=self._clock.now() + self._timeout,
            folder=FolderAccess(folder=str(folder), write=write, broad=_is_broad(folder)),
        )
        waiter = self._registry.open(approval.id)
        self._inbox.put(ApprovalNeeded(approval))
        try:
            answer = await waiter
        finally:
            self._registry.discard(approval.id)
        if answer is ApprovalDecision.WRITE:
            return FolderResult(True, True, "the host opened the folder for reading and writing")
        if answer is ApprovalDecision.READ:
            return FolderResult(True, False, "the host opened the folder for reading only")
        return FolderResult(False, False, f"the host did not open {folder}. {FINAL}")

    async def check(
        self, call: ToolCallView, *, subject: str, provenance: Provenance
    ) -> GateResult:
        invocation = ToolInvocation(name=call.name, risk=call.risk, subject=subject)
        decision = evaluate(self._policy, invocation, provenance)
        refused = decision.action is PolicyAction.DENY or decision.reason == PLAN_MODE
        verdict = None
        if self._guard is not None and not refused:
            verdict = await self._guard(call, provenance)
        if verdict is not None and verdict.action == "deny":
            reason = f"refused by the {verdict.plugin} plugin: {verdict.reason}"
            return GateResult(allowed=False, reason=f"{reason}. {FINAL}")
        if decision.action is PolicyAction.ALLOW and verdict is None:
            return GateResult(allowed=True, reason=decision.reason)
        if decision.reason == PLAN_MODE:
            return GateResult(allowed=False, reason=PLAN_MODE)
        if decision.action is PolicyAction.DENY:
            return GateResult(allowed=False, reason=f"{decision.reason}. {FINAL}")
        if self._rejections.exhausted(invocation):
            return GateResult(allowed=False, reason=f"rejected by the host repeatedly. {FINAL}")
        approval = ApprovalView(
            id=self._ids.new("ap_"),
            call=call,
            provenance=provenance,
            timeout_at=self._clock.now() + self._timeout,
            suggested_patterns=decision.suggested_patterns,
            warnings=() if verdict is None else (f"{verdict.plugin} plugin: {verdict.reason}",),
        )
        waiter = self._registry.open(approval.id)
        self._inbox.put(ApprovalNeeded(approval))
        try:
            answer = await waiter
        finally:
            self._registry.discard(approval.id)
        if answer is ApprovalDecision.REJECT:
            self._rejections.record(invocation)
            return GateResult(allowed=False, reason=f"rejected by the host. {FINAL}")
        if answer is ApprovalDecision.BLOCK:
            return GateResult(allowed=False, reason=f"blocked by the host. {FINAL}")
        return GateResult(allowed=True, reason=f"approved by host ({answer})")


def _is_broad(folder: Path) -> bool:
    """The filesystem root, the home folder, or a folder that holds the home folder."""
    home = Path.home().resolve()
    return folder == Path(folder.anchor) or home.is_relative_to(folder)
