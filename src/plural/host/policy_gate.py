from datetime import timedelta
from typing import Final

from plural.agent.gate import GateResult
from plural.core.policy.engine import PLAN_MODE, Policy, ToolInvocation, evaluate, run_limit
from plural.core.policy.rejections import RejectionLedger
from plural.core.policy.rules import RuleSet
from plural.core.ports import Clock, IdGenerator
from plural.host.approval_registry import ApprovalRegistry
from plural.host.inbox import ApprovalNeeded, Inbox
from plural.protocol.models import (
    ApprovalDecision,
    ApprovalView,
    PermissionMode,
    PolicyAction,
    Provenance,
    ToolCallView,
    Usage,
)

FINAL: Final = "Do not retry this or an equivalent action; ask the user how to proceed instead"


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
    ) -> None:
        self._policy = policy
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

    async def check(
        self, call: ToolCallView, *, subject: str, provenance: Provenance
    ) -> GateResult:
        invocation = ToolInvocation(name=call.name, risk=call.risk, subject=subject)
        decision = evaluate(self._policy, invocation, provenance)
        if decision.action is PolicyAction.ALLOW:
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
