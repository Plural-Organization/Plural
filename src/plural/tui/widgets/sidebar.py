from rich.text import Text
from textual.widgets import Static

from plural.protocol.models import SessionState


class ParticipantsPanel(Static):
    def refresh_from(self, state: SessionState) -> None:
        text = Text("Participants\n", style="bold")
        for participant in state.participants.values():
            marker = "●" if participant.connected else "○"
            text.append(f"{marker} {participant.name} ({participant.role})\n")
        self.update(text)


class ProposalsPanel(Static):
    def refresh_from(self, state: SessionState) -> None:
        text = Text(f"Proposals ({len(state.proposals)})\n", style="bold")
        for proposal in state.proposals.values():
            author = state.participants.get(proposal.author_id)
            text.append(f"• {author.name if author else '?'}: {proposal.text[:60]}\n")
        if state.approvals:
            text.append(f"\nPending approvals: {len(state.approvals)}\n", style="magenta")
        self.update(text)
