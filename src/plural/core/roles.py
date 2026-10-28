from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from plural.core.errors import Forbidden
from plural.protocol.commands import (
    AdmissionSet,
    ApprovalRespond,
    BoardClear,
    BoardDraw,
    BoardErase,
    BoardOpen,
    ChatSend,
    Command,
    ContextCompact,
    CursorSet,
    FileAttach,
    HistoryGet,
    InviteCreate,
    JoinDecide,
    LinkRevoke,
    McpAdd,
    McpImport,
    McpRemove,
    McpRestart,
    McpToggle,
    ParticipantRevoke,
    ParticipantSetRole,
    PermissionModeSet,
    PolicyAdd,
    PolicyRemove,
    PromptModeSet,
    PromptSubmit,
    ProposalDecide,
    QueueCancel,
    RunAbort,
    SelectionSet,
    SessionHello,
    SkillsInstall,
    SkillsRemove,
    SkillsSearch,
    TypingSet,
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
        ChatSend: CONTRIBUTORS,
        FileAttach: CONTRIBUTORS,
        ProposalDecide: HOST_ONLY,
        ApprovalRespond: HOST_ONLY,
        RunAbort: HOST_ONLY,
        ContextCompact: HOST_ONLY,
        InviteCreate: HOST_ONLY,
        JoinDecide: HOST_ONLY,
        LinkRevoke: HOST_ONLY,
        AdmissionSet: HOST_ONLY,
        ParticipantSetRole: HOST_ONLY,
        ParticipantRevoke: HOST_ONLY,
        PolicyAdd: HOST_ONLY,
        PolicyRemove: HOST_ONLY,
        PromptModeSet: HOST_ONLY,
        PermissionModeSet: HOST_ONLY,
        SkillsSearch: CONTRIBUTORS,
        SkillsInstall: HOST_ONLY,
        SkillsRemove: HOST_ONLY,
        McpAdd: HOST_ONLY,
        McpRemove: HOST_ONLY,
        McpToggle: HOST_ONLY,
        McpRestart: HOST_ONLY,
        McpImport: HOST_ONLY,
        TypingSet: CONTRIBUTORS,
        SelectionSet: EVERYONE,
        CursorSet: EVERYONE,
        BoardOpen: CONTRIBUTORS,
        BoardDraw: CONTRIBUTORS,
        BoardErase: CONTRIBUTORS,
        BoardClear: HOST_ONLY,
        QueueCancel: CONTRIBUTORS,
    }
)


def can(role: Role, command: Command) -> bool:
    return role in PERMISSIONS.get(type(command), frozenset())


def authorize(role: Role, command: Command) -> None:
    if not can(role, command):
        raise Forbidden(f"{role} cannot {command.type}")
