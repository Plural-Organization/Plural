import json
from typing import Final

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from plural.protocol.models import ApprovalDecision, ApprovalView, ProposalDecision, ProposalView

DIALOG_CSS: Final = """
#dialog { width: 80; height: auto; padding: 1 2; border: thick $accent; background: $surface; }
#dialog Horizontal { height: auto; margin-top: 1; }
#dialog Button { margin-right: 1; }
"""


class ApprovalDialog(ModalScreen[ApprovalDecision]):
    DEFAULT_CSS = f"ApprovalDialog {{ align: center middle; }}\n{DIALOG_CSS}"

    def __init__(self, approval: ApprovalView) -> None:
        super().__init__()
        self.approval = approval

    def compose(self) -> ComposeResult:
        call = self.approval.call
        with Vertical(id="dialog"):
            yield Label(f"The agent wants to use {call.name} [{call.risk}]")
            yield Static(call.subject or json.dumps(call.args, indent=2))
            yield Label(f"origin: {self.approval.provenance.origin}")
            with Horizontal():
                yield Button("Once", id=ApprovalDecision.ONCE.value, variant="primary")
                yield Button("Always (session)", id=ApprovalDecision.ALWAYS.value)
                yield Button("Reject", id=ApprovalDecision.REJECT.value, variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(ApprovalDecision(event.button.id or ApprovalDecision.REJECT.value))


class ProposalDialog(ModalScreen[ProposalDecision]):
    DEFAULT_CSS = f"ProposalDialog {{ align: center middle; }}\n{DIALOG_CSS}"

    def __init__(self, proposal: ProposalView, author: str) -> None:
        super().__init__()
        self.proposal = proposal
        self.author = author

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"{self.author} proposes:")
            yield Static(self.proposal.text)
            with Horizontal():
                yield Button("Approve", id=ProposalDecision.APPROVE.value, variant="primary")
                yield Button("Reject", id=ProposalDecision.REJECT.value, variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(ProposalDecision(event.button.id or ProposalDecision.REJECT.value))
