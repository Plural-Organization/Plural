from plural.core.errors import Invalid, NotFound
from plural.core.policy.engine import ToolInvocation
from plural.core.policy.rejections import class_patterns
from plural.core.policy.rules import Rule, RuleSet
from plural.protocol.events import PolicyRuleAdded, PolicyRuleRemoved
from plural.protocol.models import (
    ApprovalDecision,
    PolicyAction,
    PolicyRuleView,
    SessionState,
)


def to_rules(views: tuple[PolicyRuleView, ...]) -> RuleSet:
    return RuleSet(
        rules=tuple(Rule(tool=v.tool, pattern=v.pattern, action=v.action) for v in views)
    )


def to_views(rules: RuleSet, *, prefix: str) -> tuple[PolicyRuleView, ...]:
    return tuple(
        PolicyRuleView(id=f"{prefix}{index}", tool=r.tool, pattern=r.pattern, action=r.action)
        for index, r in enumerate(rules.rules, 1)
    )


def in_effect(state: SessionState, tool: str, pattern: str, action: PolicyAction) -> bool:
    latest = next(
        (r for r in reversed(state.policy) if (r.tool, r.pattern) == (tool, pattern)), None
    )
    return latest is not None and latest.action is action


def add(
    state: SessionState, *, rule_id: str, tool: str, pattern: str, action: PolicyAction
) -> PolicyRuleAdded:
    if not tool.strip() or not pattern.strip():
        raise Invalid("tool and pattern must not be blank")
    if in_effect(state, tool, pattern, action):
        raise Invalid("rule is already in effect")
    return PolicyRuleAdded(
        rule=PolicyRuleView(id=rule_id, tool=tool, pattern=pattern, action=action)
    )


def remove(state: SessionState, rule_id: str) -> PolicyRuleRemoved:
    if all(rule.id != rule_id for rule in state.policy):
        raise NotFound(f"rule {rule_id}")
    return PolicyRuleRemoved(rule_id=rule_id)


def from_decision(
    state: SessionState, *, approval_id: str, decision: ApprovalDecision
) -> tuple[tuple[str, str, PolicyAction], ...]:
    approval = state.approvals.get(approval_id)
    if approval is None:
        return ()
    call = approval.call
    match decision:
        case ApprovalDecision.ALWAYS:
            return tuple((call.name, p, PolicyAction.ALLOW) for p in approval.suggested_patterns)
        case ApprovalDecision.BLOCK:
            invocation = ToolInvocation(name=call.name, risk=call.risk, subject=call.subject)
            return tuple((call.name, p, PolicyAction.DENY) for p in class_patterns(invocation))
        case _:
            return ()
