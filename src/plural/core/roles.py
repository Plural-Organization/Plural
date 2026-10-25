from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from plural.core.errors import Forbidden
from plural.protocol.commands import (
    ApprovalRespond,
    Command,
    ContextCompact,
    FileAttach,
    HistoryGet,
    InviteCreate,
    ParticipantRevoke,
    ParticipantSetRole,
    PolicyAdd,
    PolicyRemove,
    PromptSubmit,
    ProposalDecide,
    RunAbort,
    SessionHello,
)
from plural.protocol.models import Model, Role

EVERYONE: Final = frozenset(Role)
CONTRIBUTORS: Final = frozenset({Role.HOST, Role.PARTICIPANT})
HOST_ONLY: Final = frozenset({Role.HOST})

PERMISSIONS: Final[Mapping[type[Model], frozenset[Role]]] = MappingProxyType(
    {
        SessionHello: EVERYONE,
        HistoryGet: EVERYONE,
        PromptSubmit: CONTRIBUTORS,
        FileAttach: CONTRIBUTORS,
        ProposalDecide: HOST_ONLY,
        ApprovalRespond: HOST_ONLY,
        RunAbort: HOST_ONLY,
        ContextCompact: HOST_ONLY,
        InviteCreate: HOST_ONLY,
        ParticipantSetRole: HOST_ONLY,
        ParticipantRevoke: HOST_ONLY,
        PolicyAdd: HOST_ONLY,
        PolicyRemove: HOST_ONLY,
    }
)


def can(role: Role, command: Command) -> bool:
    return role in PERMISSIONS.get(type(command), frozenset())


def authorize(role: Role, command: Command) -> None:
    if not can(role, command):
        raise Forbidden(f"{role} cannot {command.type}")
