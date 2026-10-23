from collections.abc import Iterable

from plural.core.errors import NotFound
from plural.protocol.commands import PromptSubmit, ProposalDecide
from plural.protocol.events import ProposalApproved, ProposalCreated, ProposalRejected
from plural.protocol.models import ProposalDecision, ProposalView, SessionState


def submit(
    state: SessionState, *, proposal_id: str, author_id: str, command: PromptSubmit
) -> ProposalCreated:
    ensure_attachments(state, command.attachments)
    proposal = ProposalView(
        id=proposal_id,
        author_id=author_id,
        text=command.text,
        delivery=command.delivery,
        attachments=command.attachments,
    )
    return ProposalCreated(proposal=proposal)


def decide(
    state: SessionState, *, decided_by: str, command: ProposalDecide
) -> ProposalApproved | ProposalRejected:
    proposal = state.proposals.get(command.proposal_id)
    if proposal is None:
        raise NotFound(f"proposal {command.proposal_id}")
    if command.decision is ProposalDecision.REJECT:
        return ProposalRejected(proposal_id=proposal.id, decided_by=decided_by)
    text = command.edited_text or proposal.text
    return ProposalApproved(proposal_id=proposal.id, decided_by=decided_by, text=text)


def ensure_attachments(state: SessionState, attachment_ids: Iterable[str]) -> None:
    missing = [a for a in attachment_ids if a not in state.attachments]
    if missing:
        raise NotFound(f"attachments {', '.join(missing)}")
