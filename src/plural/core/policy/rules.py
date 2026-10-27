from collections.abc import Mapping
from fnmatch import fnmatchcase
from typing import Final, Self

from plural.protocol.models import Model, PolicyAction


class Rule(Model):
    tool: str
    pattern: str
    action: PolicyAction

    def matches(self, tool: str, subject: str) -> bool:
        return fnmatchcase(tool, self.tool) and fnmatchcase(subject, self.pattern)


class RuleSet(Model):
    rules: tuple[Rule, ...] = ()

    def resolve(self, tool: str, subject: str) -> PolicyAction | None:
        for rule in reversed(self.rules):
            if rule.matches(tool, subject):
                return rule.action
        return None

    def extended(self, *rules: Rule) -> Self:
        return self.model_copy(update={"rules": (*self.rules, *rules)})

    @classmethod
    def from_mapping(cls, spec: Mapping[str, Mapping[str, str]]) -> Self:
        rules = tuple(
            Rule(tool=tool, pattern=pattern, action=PolicyAction(action))
            for tool, patterns in spec.items()
            for pattern, action in patterns.items()
        )
        return cls(rules=rules)


DEFAULT_RULES: Final = RuleSet.from_mapping(
    {
        "read": {"*": "allow", "*.env*": "deny", "*.pem": "deny", "*.key": "deny"},
        "grep": {"*": "allow"},
        "glob": {"*": "allow"},
        "ls": {"*": "allow"},
        "web_search": {"*": "ask"},
        "web_fetch": {"*": "ask"},
        "write": {"*": "ask"},
        "edit": {"*": "ask"},
        "multi_edit": {"*": "ask"},
        "bash": {
            "*": "ask",
            "git status*": "allow",
            "git diff*": "allow",
            "ls*": "allow",
            "rm -rf*": "deny",
        },
    }
)
