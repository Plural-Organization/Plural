from typing import Final

from plural.core.policy.engine import ToolInvocation
from plural.protocol.models import ToolRisk

SUBCOMMAND_TOOLS: Final = frozenset(
    {"git", "npm", "pnpm", "yarn", "cargo", "docker", "kubectl", "uv", "pip", "go", "make"}
)


def command_class(command: str) -> str:
    tokens = command.split()
    if not tokens:
        return ""
    if tokens[0] in SUBCOMMAND_TOOLS and len(tokens) > 1:
        return f"{tokens[0]} {tokens[1]}"
    return tokens[0]


def invocation_class(invocation: ToolInvocation) -> str:
    if invocation.risk is ToolRisk.EXEC:
        return command_class(invocation.subject)
    return invocation.subject


def class_patterns(invocation: ToolInvocation) -> tuple[str, ...]:
    kind = invocation_class(invocation)
    if invocation.risk is ToolRisk.EXEC and kind:
        return (kind, f"{kind} *")
    return (invocation.subject,)


class RejectionLedger:
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._counts: dict[tuple[str, str], int] = {}

    def reset(self) -> None:
        self._counts.clear()

    def record(self, invocation: ToolInvocation) -> None:
        key = (invocation.name, invocation_class(invocation))
        self._counts[key] = self._counts.get(key, 0) + 1

    def exhausted(self, invocation: ToolInvocation) -> bool:
        return self._counts.get((invocation.name, invocation_class(invocation)), 0) >= self._limit
