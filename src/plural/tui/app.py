from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input

from plural.client.connection import CommandRejected
from plural.client.presenter import describe
from plural.client.reconnect import SessionClient
from plural.protocol.commands import (
    ApprovalRespond,
    Command,
    InviteCreate,
    PromptSubmit,
    ProposalDecide,
    RunAbort,
)
from plural.protocol.events import ApprovalRequested, ApprovalResolved, Event, SessionWelcome
from plural.protocol.models import ApprovalDecision, ApprovalView, ProposalDecision, Role
from plural.tui.widgets.dialogs import ApprovalDialog, ProposalDialog
from plural.tui.widgets.sidebar import ParticipantsPanel, ProposalsPanel
from plural.tui.widgets.transcript import LiveReply, Transcript


class PluralApp(App[None]):
    TITLE = "Plural"
    CSS = """
    #main { height: 1fr; }
    #left { width: 3fr; }
    #transcript { height: 1fr; border: round $primary; }
    LiveReply { height: auto; max-height: 8; padding: 0 1; }
    #side { width: 1fr; }
    ParticipantsPanel, ProposalsPanel { height: 1fr; border: round $secondary; padding: 0 1; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+r", "review", "Review proposal"),
        Binding("ctrl+i", "invite", "Invite"),
        Binding("ctrl+x", "abort", "Abort run"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, client: SessionClient) -> None:
        super().__init__()
        self._client = client
        self._dialogs: dict[str, ApprovalDialog] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Transcript()
                yield LiveReply()
            with Vertical(id="side"):
                yield ParticipantsPanel()
                yield ProposalsPanel()
        yield Input(placeholder="Message the agent (participants send proposals)", id="prompt")
        yield Footer()

    def on_mount(self) -> None:
        self.run_worker(self._consume(), exclusive=True, name="session")

    async def _consume(self) -> None:
        async for event in self._client.events():
            self._show(event)

    def _show(self, event: Event) -> None:
        projection = self._client.projection
        line = describe(event, projection.state)
        if line is not None:
            self.query_one(Transcript).add(line)
        self.query_one(LiveReply).show("".join(projection.streaming.values()))
        self.query_one(ParticipantsPanel).refresh_from(projection.state)
        self.query_one(ProposalsPanel).refresh_from(projection.state)
        match event:
            case SessionWelcome(participant=participant):
                self.sub_title = f"{participant.name} · {participant.role}"
            case ApprovalRequested(approval=approval) if self._is_host():
                self._ask_approval(approval)
            case ApprovalResolved(approval_id=approval_id):
                dialog = self._dialogs.pop(approval_id, None)
                if dialog is not None and dialog.is_current:
                    dialog.dismiss(None)
            case _:
                pass

    def _ask_approval(self, approval: ApprovalView) -> None:
        dialog = self._dialogs[approval.id] = ApprovalDialog(approval)

        def answer(decision: ApprovalDecision | None) -> None:
            self._dialogs.pop(approval.id, None)
            if decision is not None:
                self._send(ApprovalRespond(approval_id=approval.id, decision=decision))

        self.push_screen(dialog, answer)

    def _is_host(self) -> bool:
        me = self._client.projection.me
        return me is not None and me.role is Role.HOST

    def on_input_submitted(self, message: Input.Submitted) -> None:
        text = message.value.strip()
        message.input.clear()
        if text:
            self._send(PromptSubmit(text=text))

    def action_review(self) -> None:
        state = self._client.projection.state
        proposal = next(iter(state.proposals.values()), None)
        if proposal is None or not self._is_host():
            return
        author = state.participants.get(proposal.author_id)

        def decide(decision: ProposalDecision | None) -> None:
            if decision is not None:
                self._send(ProposalDecide(proposal_id=proposal.id, decision=decision))

        self.push_screen(ProposalDialog(proposal, author.name if author else "?"), decide)

    def action_invite(self) -> None:
        self._send(InviteCreate())

    def action_abort(self) -> None:
        self._send(RunAbort())

    def _send(self, command: Command) -> None:
        async def deliver() -> None:
            try:
                await self._client.send(command)
            except (CommandRejected, ConnectionError, TimeoutError) as error:
                self.notify(str(error), severity="error")

        self.run_worker(deliver(), group="commands")
