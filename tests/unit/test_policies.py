from datetime import UTC, datetime

import pytest

from plural.client.slash import ShowPolicy, SlashError, parse
from plural.core import policies
from plural.core.errors import Invalid, NotFound
from plural.core.policy.rules import DEFAULT_RULES
from plural.core.provenance import direct
from plural.core.state import reduce
from plural.protocol.commands import PolicyAdd, PolicyRemove, RunAbort
from plural.protocol.events import (
    EventRecord,
    PolicyRuleAdded,
    PolicyRuleRemoved,
)
from plural.protocol.models import (
    ApprovalDecision,
    ApprovalView,
    PolicyAction,
    PolicyRuleView,
    Role,
    SessionState,
    ToolCallView,
    ToolRisk,
)

TS = datetime(2026, 10, 25, tzinfo=UTC)


def rule(rule_id: str, pattern: str, action: PolicyAction) -> PolicyRuleView:
    return PolicyRuleView(id=rule_id, tool="bash", pattern=pattern, action=action)


def state_with(*rules: PolicyRuleView) -> SessionState:
    return SessionState(policy=rules)


def approval_state(command: str, patterns: tuple[str, ...]) -> SessionState:
    call = ToolCallView(id="c1", name="bash", risk=ToolRisk.EXEC, subject=command)
    approval = ApprovalView(
        id="ap_1",
        call=call,
        provenance=direct("p_host", Role.HOST),
        timeout_at=TS,
        suggested_patterns=patterns,
    )
    return SessionState(approvals={"ap_1": approval})


def test_events_append_and_remove_in_order() -> None:
    first, second = (
        rule("pl_1", "make *", PolicyAction.ALLOW),
        rule("pl_2", "ls*", PolicyAction.ASK),
    )
    state = SessionState()
    for seq, event in enumerate(
        [
            PolicyRuleAdded(rule=first),
            PolicyRuleAdded(rule=second),
            PolicyRuleRemoved(rule_id="pl_1"),
        ],
        1,
    ):
        state = reduce(state, EventRecord(seq=seq, id=f"e{seq}", ts=TS, actor_id=None, event=event))
    assert state.policy == (second,)


def test_add_rejects_blank_and_duplicate_rules() -> None:
    with pytest.raises(Invalid):
        policies.add(
            SessionState(), rule_id="pl_1", tool=" ", pattern="x", action=PolicyAction.ALLOW
        )
    existing = state_with(rule("pl_1", "make *", PolicyAction.ALLOW))
    with pytest.raises(Invalid):
        policies.add(
            existing, rule_id="pl_2", tool="bash", pattern="make *", action=PolicyAction.ALLOW
        )


def test_a_superseded_rule_can_be_added_again() -> None:
    state = state_with(
        rule("pl_1", "make *", PolicyAction.ALLOW), rule("pl_2", "make *", PolicyAction.DENY)
    )
    assert policies.in_effect(state, "bash", "make *", PolicyAction.DENY)
    assert not policies.in_effect(state, "bash", "make *", PolicyAction.ALLOW)
    added = policies.add(
        state, rule_id="pl_3", tool="bash", pattern="make *", action=PolicyAction.ALLOW
    )
    assert added.rule.id == "pl_3"


def test_remove_unknown_rule() -> None:
    with pytest.raises(NotFound):
        policies.remove(SessionState(), "pl_9")
    assert (
        policies.remove(state_with(rule("pl_1", "x", PolicyAction.ASK)), "pl_1").rule_id == "pl_1"
    )


def test_decisions_turn_into_rules() -> None:
    state = approval_state("pytest -q", ("pytest -q*",))
    always = policies.from_decision(state, approval_id="ap_1", decision=ApprovalDecision.ALWAYS)
    assert always == (("bash", "pytest -q*", PolicyAction.ALLOW),)
    block = policies.from_decision(state, approval_id="ap_1", decision=ApprovalDecision.BLOCK)
    assert block == (
        ("bash", "pytest", PolicyAction.DENY),
        ("bash", "pytest *", PolicyAction.DENY),
    )
    for decision in (ApprovalDecision.ONCE, ApprovalDecision.REJECT):
        assert policies.from_decision(state, approval_id="ap_1", decision=decision) == ()
    assert policies.from_decision(state, approval_id="nope", decision=ApprovalDecision.ALWAYS) == ()


def test_base_rules_are_listed_with_stable_ids() -> None:
    views = policies.to_views(DEFAULT_RULES, prefix="base")
    assert views[0].id == "base1"
    assert any(v.action is PolicyAction.DENY and v.pattern == "rm -rf*" for v in views)


def test_slash_commands() -> None:
    assert parse("just a prompt") is None
    assert isinstance(parse("/abort"), RunAbort)
    assert isinstance(parse("/policy"), ShowPolicy)
    assert parse("/policy allow bash make *") == PolicyAdd(
        tool="bash", pattern="make *", action=PolicyAction.ALLOW
    )
    assert parse("/policy rm pl_1") == PolicyRemove(rule_id="pl_1")


@pytest.mark.parametrize(
    "text", ["/nope", "/policy allow", "/policy allow bash", "/policy permit bash x", "/policy rm"]
)
def test_slash_errors(text: str) -> None:
    with pytest.raises(SlashError):
        parse(text)
