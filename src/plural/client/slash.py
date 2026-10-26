from dataclasses import dataclass

from plural.protocol.commands import (
    Command,
    ContextCompact,
    PolicyAdd,
    PolicyRemove,
    PromptModeSet,
    RunAbort,
)
from plural.protocol.models import PolicyAction, PromptMode

MODE_USAGE = "usage: /mode open|review"
USAGE = "usage: /policy | /policy allow|ask|deny <tool> <pattern> | /policy rm <rule id>"


class SlashError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ShowPolicy:
    pass


def parse(text: str) -> Command | ShowPolicy | None:
    if not text.startswith("/"):
        return None
    name, _, rest = text[1:].partition(" ")
    match name:
        case "abort":
            return RunAbort()
        case "compact":
            return ContextCompact()
        case "mode":
            return _mode(rest.strip())
        case "policy":
            return _policy(rest.strip())
        case _:
            raise SlashError(f"unknown command /{name}")


def _mode(argument: str) -> Command:
    try:
        return PromptModeSet(mode=PromptMode(argument))
    except ValueError:
        raise SlashError(MODE_USAGE) from None


def _policy(arguments: str) -> Command | ShowPolicy:
    if not arguments:
        return ShowPolicy()
    verb, _, rest = arguments.partition(" ")
    if verb == "rm":
        rule_id = rest.strip()
        if not rule_id:
            raise SlashError(USAGE)
        return PolicyRemove(rule_id=rule_id)
    try:
        action = PolicyAction(verb)
    except ValueError:
        raise SlashError(USAGE) from None
    tool, _, pattern = rest.strip().partition(" ")
    if not tool or not pattern.strip():
        raise SlashError(USAGE)
    return PolicyAdd(tool=tool, pattern=pattern.strip(), action=action)
