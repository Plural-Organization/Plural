import re
from typing import Final, Self

from plural.core.policy.rules import DEFAULT_RULES, RuleSet
from plural.core.provenance import is_guest_originated
from plural.protocol.models import Model, PolicyAction, Provenance, ToolRisk

COMPOUND_SHELL: Final = re.compile(r"[;&|`$<>()\n]")


class ToolInvocation(Model):
    name: str
    risk: ToolRisk
    subject: str


class Decision(Model):
    action: PolicyAction
    reason: str
    suggested_patterns: tuple[str, ...] = ()


class Policy(Model):
    rules: RuleSet = DEFAULT_RULES
    session: RuleSet = RuleSet()
    guest_taint: frozenset[ToolRisk] = frozenset({ToolRisk.WRITE, ToolRisk.EXEC})
    default: PolicyAction = PolicyAction.ASK

    def with_session(self, session: RuleSet) -> Self:
        return self.model_copy(update={"session": session})


def evaluate(policy: Policy, invocation: ToolInvocation, provenance: Provenance) -> Decision:
    base = policy.rules.resolve(invocation.name, invocation.subject)
    if base is PolicyAction.DENY:
        return Decision(action=PolicyAction.DENY, reason="denied by policy rule")
    session = policy.session.resolve(invocation.name, invocation.subject)
    action = session or base or policy.default
    reason = "session rule" if session else "policy rule" if base else "default"
    if action is PolicyAction.ALLOW:
        if invocation.risk in policy.guest_taint and is_guest_originated(provenance):
            action, reason = PolicyAction.ASK, "guest-originated turn"
        elif invocation.risk is ToolRisk.EXEC and COMPOUND_SHELL.search(invocation.subject):
            action, reason = PolicyAction.ASK, "compound shell command"
    suggested = suggest_patterns(invocation) if action is PolicyAction.ASK else ()
    return Decision(action=action, reason=reason, suggested_patterns=suggested)


def suggest_patterns(invocation: ToolInvocation) -> tuple[str, ...]:
    if invocation.risk is not ToolRisk.EXEC:
        return (invocation.subject,)
    if COMPOUND_SHELL.search(invocation.subject):
        return (invocation.subject,)
    tokens = invocation.subject.split()
    return (f"{' '.join(tokens[:2])}*",) if tokens else ()
