from datetime import timedelta
from typing import Final

from plural.agent.gate import GateResult
from plural.core.policy.engine import Policy, ToolInvocation, evaluate
from plural.core.policy.rejections import RejectionLedger, class_patterns
from plural.core.policy.rules import Action
from plural.core.ports import Clock, IdGenerator
from plural.host.approval_registry import ApprovalRegistry
from plural.host.inbox import ApprovalNeeded, Inbox
from plural.protocol.models import ApprovalDecision, ApprovalView, Provenance, ToolCallView

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

    def begin_run(self) -> None:
        self._rejections.reset()

    async def check(
        self, call: ToolCallView, *, subject: str, provenance: Provenance
    ) -> GateResult:
        invocation = ToolInvocation(name=call.name, risk=call.risk, subject=subject)
        decision = evaluate(self._policy, invocation, provenance)
        if decision.action is Action.ALLOW:
            return GateResult(allowed=True, reason=decision.reason)
        if decision.action is Action.DENY:
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
            self._policy = self._policy.deny_always(call.name, class_patterns(invocation))
            return GateResult(allowed=False, reason=f"blocked by the host. {FINAL}")
        if answer is ApprovalDecision.ALWAYS:
            self._policy = self._policy.allow_always(call.name, decision.suggested_patterns)
        return GateResult(allowed=True, reason=f"approved by host ({answer})")
