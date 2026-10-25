import pytest

from plural.core.policy.engine import Policy, ToolInvocation, evaluate
from plural.core.policy.rejections import (
    RejectionLedger,
    class_patterns,
    command_class,
    invocation_class,
)
from plural.core.policy.rules import Rule, RuleSet
from plural.core.provenance import direct
from plural.protocol.models import PolicyAction, Role, ToolRisk


def bash(command: str) -> ToolInvocation:
    return ToolInvocation(name="bash", risk=ToolRisk.EXEC, subject=command)


def edit(path: str) -> ToolInvocation:
    return ToolInvocation(name="edit", risk=ToolRisk.WRITE, subject=path)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("rm notes.txt", "rm"),
        ("rm -f notes.txt", "rm"),
        ("git push origin main", "git push"),
        ("git status", "git status"),
        ("uv run pytest", "uv run"),
        ("pytest -q", "pytest"),
        ("git", "git"),
        ("", ""),
    ],
)
def test_command_class(command: str, expected: str) -> None:
    assert command_class(command) == expected


def test_flags_do_not_change_the_class() -> None:
    assert invocation_class(bash("rm a")) == invocation_class(bash("rm -f a"))
    assert invocation_class(bash("git push")) != invocation_class(bash("git status"))
    assert invocation_class(edit("src/a.py")) != invocation_class(edit("src/b.py"))


def test_class_patterns_cover_arguments_but_not_lookalikes() -> None:
    from fnmatch import fnmatchcase

    patterns = class_patterns(bash("rm -f a"))
    assert any(fnmatchcase("rm b", p) for p in patterns)
    assert any(fnmatchcase("rm", p) for p in patterns)
    assert not any(fnmatchcase("rmdir b", p) for p in patterns)


def test_ledger_exhausts_per_class_and_resets() -> None:
    ledger = RejectionLedger(limit=2)
    ledger.record(bash("rm a"))
    assert not ledger.exhausted(bash("rm b"))
    ledger.record(bash("rm -f a"))
    assert ledger.exhausted(bash("rm c"))
    assert not ledger.exhausted(bash("ls"))
    assert not ledger.exhausted(edit("rm"))
    ledger.reset()
    assert not ledger.exhausted(bash("rm c"))


def session(tool: str, patterns: tuple[str, ...], action: PolicyAction) -> Policy:
    rules = tuple(Rule(tool=tool, pattern=p, action=action) for p in patterns)
    return Policy().with_session(RuleSet(rules=rules))


def test_blocked_class_is_denied_for_the_session() -> None:
    host = direct("p_host", Role.HOST)
    invocation = bash("curl example.com")
    assert evaluate(Policy(), invocation, host).action is PolicyAction.ASK
    blocked = session("bash", class_patterns(invocation), PolicyAction.DENY)
    assert evaluate(blocked, bash("curl -s other.org"), host).action is PolicyAction.DENY
    assert evaluate(blocked, bash("ls"), host).action is PolicyAction.ALLOW


def test_block_overrides_an_earlier_always() -> None:
    host = direct("p_host", Role.HOST)
    patterns = class_patterns(bash("make deploy staging"))
    allowed = tuple(Rule(tool="bash", pattern=p, action=PolicyAction.ALLOW) for p in patterns)
    denied = tuple(Rule(tool="bash", pattern=p, action=PolicyAction.DENY) for p in patterns)
    policy = Policy().with_session(RuleSet(rules=allowed))
    assert evaluate(policy, bash("make deploy x"), host).action is PolicyAction.ALLOW
    policy = policy.with_session(RuleSet(rules=(*allowed, *denied)))
    assert evaluate(policy, bash("make deploy x"), host).action is PolicyAction.DENY
