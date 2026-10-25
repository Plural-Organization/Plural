from collections.abc import Callable

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList, Select, Static
from textual.widgets.option_list import Option

from plural.client.presenter import rule_line
from plural.protocol.commands import Command, PolicyAdd, PolicyRemove
from plural.protocol.models import PolicyAction, PolicyRuleView

CSS = """
PoliciesDialog { align: center middle; }
#policies { width: 90; height: auto; max-height: 90%; padding: 1 2; border: thick $accent;
    background: $surface; }
#policies OptionList { height: 8; }
#policies #base { height: auto; max-height: 8; color: $text-muted; }
#policies Horizontal { height: auto; margin-top: 1; }
#policies Select { width: 14; }
#policies #tool { width: 14; }
#policies #pattern { width: 1fr; }
#policies Button { margin-left: 1; }
"""


class PoliciesDialog(ModalScreen[None]):
    DEFAULT_CSS = CSS
    BINDINGS = [("escape", "dismiss(None)", "Close")]  # noqa: RUF012

    def __init__(
        self,
        base: tuple[PolicyRuleView, ...],
        session: tuple[PolicyRuleView, ...],
        send: Callable[[Command], None],
    ) -> None:
        super().__init__()
        self._base = base
        self._session = session
        self._send = send
        self._rules = OptionList(id="rules")
        self._action = Select[PolicyAction](
            [(a.value, a) for a in PolicyAction], value=PolicyAction.ALLOW, allow_blank=False
        )
        self._tool = Input(value="bash", placeholder="tool", id="tool")
        self._pattern = Input(placeholder="pattern, e.g. make *", id="pattern")

    def compose(self) -> ComposeResult:
        with Vertical(id="policies"):
            yield Label("Session rules (the last matching rule wins)")
            yield self._rules
            yield Label("Built-in rules (read-only, deny always wins)")
            yield Static("\n".join(rule_line(rule) for rule in self._base), id="base")
            with Horizontal():
                yield self._action
                yield self._tool
                yield self._pattern
                yield Button("Add", id="add", variant="primary")
            with Horizontal():
                yield Button("Remove selected", id="remove", variant="warning")
                yield Button("Close", id="close")

    def on_mount(self) -> None:
        self.show(self._session)

    def show(self, session: tuple[PolicyRuleView, ...]) -> None:
        highlighted = self._rules.highlighted
        self._session = session
        self._rules.clear_options()
        self._rules.add_options(
            [Option(f"{rule_line(rule)}  [{rule.id}]", id=rule.id) for rule in session]
        )
        if session:
            self._rules.highlighted = min(highlighted or 0, len(session) - 1)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "add":
                self._add()
            case "remove":
                self._remove()
            case _:
                self.dismiss(None)

    def _add(self) -> None:
        tool, pattern = self._tool.value.strip(), self._pattern.value.strip()
        action = self._action.value
        if not tool or not pattern or not isinstance(action, PolicyAction):
            self.notify("tool and pattern are required", severity="warning")
            return
        self._send(PolicyAdd(tool=tool, pattern=pattern, action=action))
        self._pattern.clear()

    def _remove(self) -> None:
        index = self._rules.highlighted
        if index is None:
            return
        rule_id = self._rules.get_option_at_index(index).id
        if rule_id is not None:
            self._send(PolicyRemove(rule_id=rule_id))
