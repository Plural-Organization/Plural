import re
from typing import Final, Self

from plural.core.policy.rules import DEFAULT_RULES, RuleSet
from plural.core.provenance import is_guest_originated
from plural.protocol.models import Model, PermissionMode, PolicyAction, Provenance, ToolRisk, Usage

COMPOUND_SHELL: Final = re.compile(r"[;&|`$<>()\n]")
PLAN_MODE: Final = (
    "plan mode is on, so nothing may change yet. Keep researching with read-only tools, then "
    "reply with a concrete plan and wait for the host to approve it"
)
GUEST_BUDGET: Final = "the token budget for a run started by a guest is used up"
UNLOCKED: Final[dict[PermissionMode, frozenset[ToolRisk]]] = {
    PermissionMode.ACCEPT_EDITS: frozenset({ToolRisk.WRITE}),
    PermissionMode.AUTO: frozenset({ToolRisk.WRITE, ToolRisk.EXEC}),
}


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
    mode: PermissionMode = PermissionMode.DEFAULT
    guest_run_tokens: int | None = None

    def with_session(self, session: RuleSet) -> Self:
        return self.model_copy(update={"session": session})

    def with_mode(self, mode: PermissionMode) -> Self:
        return self.model_copy(update={"mode": mode})


def evaluate(policy: Policy, invocation: ToolInvocation, provenance: Provenance) -> Decision:
    base = policy.rules.resolve(invocation.name, invocation.subject)
    if base is PolicyAction.DENY:
        return Decision(action=PolicyAction.DENY, reason="denied by policy rule")
    session = policy.session.resolve(invocation.name, invocation.subject)
    action = session or base or policy.default
    reason = "session rule" if session else "policy rule" if base else "default"
    if policy.mode is PermissionMode.PLAN and _changes_things(invocation, action):
        return Decision(action=PolicyAction.DENY, reason=PLAN_MODE)
    unlocked = invocation.risk in UNLOCKED.get(policy.mode, frozenset())
    if action is PolicyAction.ASK and unlocked:
        action, reason = PolicyAction.ALLOW, f"{policy.mode} mode"
    if action is PolicyAction.ALLOW:
        if invocation.risk in policy.guest_taint and is_guest_originated(provenance):
            action, reason = PolicyAction.ASK, "guest-originated turn"
        elif (
            invocation.risk is ToolRisk.EXEC
            and COMPOUND_SHELL.search(invocation.subject)
            and not unlocked
        ):
            action, reason = PolicyAction.ASK, "compound shell command"
    suggested = suggest_patterns(invocation) if action is PolicyAction.ASK else ()
    return Decision(action=action, reason=reason, suggested_patterns=suggested)


def run_limit(policy: Policy, usage: Usage, provenance: Provenance) -> str | None:
    if policy.guest_run_tokens is None or not is_guest_originated(provenance):
        return None
    # Cache reads cost a fraction of fresh input, so they do not count against the budget.
    billed = usage.input_tokens + usage.cache_write_tokens + usage.output_tokens
    return GUEST_BUDGET if billed >= policy.guest_run_tokens else None


def _changes_things(invocation: ToolInvocation, action: PolicyAction) -> bool:
    if invocation.risk is ToolRisk.WRITE:
        return True
    if invocation.risk is ToolRisk.EXEC:
        return action is not PolicyAction.ALLOW or bool(COMPOUND_SHELL.search(invocation.subject))
    return False


def suggest_patterns(invocation: ToolInvocation) -> tuple[str, ...]:
    if invocation.risk is not ToolRisk.EXEC:
        return (invocation.subject,)
    if COMPOUND_SHELL.search(invocation.subject):
        return (invocation.subject,)
    tokens = invocation.subject.split()
    return (f"{' '.join(tokens[:2])}*",) if tokens else ()
