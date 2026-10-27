import pytest

from plural.core.errors import Forbidden
from plural.core.roles import authorize, can
from plural.protocol.commands import (
    HistoryGet,
    PermissionModeSet,
    PromptModeSet,
    PromptSubmit,
    ProposalDecide,
    RunAbort,
)
from plural.protocol.models import PermissionMode, PromptMode, ProposalDecision, Role


def test_matrix() -> None:
    decide = ProposalDecide(proposal_id="pr_1", decision=ProposalDecision.APPROVE)
    assert can(Role.VIEWER, HistoryGet())
    assert not can(Role.VIEWER, PromptSubmit(text="x"))
    assert can(Role.PARTICIPANT, PromptSubmit(text="x"))
    assert not can(Role.PARTICIPANT, decide)
    assert can(Role.HOST, decide)
    with pytest.raises(Forbidden):
        authorize(Role.PARTICIPANT, RunAbort())
    switch = PromptModeSet(mode=PromptMode.REVIEW)
    assert can(Role.HOST, switch)
    assert not can(Role.PARTICIPANT, switch)
    assert not can(Role.VIEWER, switch)
    auto = PermissionModeSet(mode=PermissionMode.AUTO)
    assert can(Role.HOST, auto)
    assert not can(Role.PARTICIPANT, auto)
