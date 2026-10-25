from collections.abc import Callable
from pathlib import Path

from textual.pilot import Pilot
from textual.widgets import Input, OptionList

from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.client.presenter import live
from plural.client.reconnect import JoinLink, SessionClient
from plural.protocol.commands import PromptSubmit
from plural.tui.app import PluralApp
from plural.tui.widgets.dialogs import ApprovalDialog, ProposalDialog
from plural.tui.widgets.policy import PoliciesDialog
from plural.tui.widgets.transcript import Transcript
from tests.e2e.support import CLIENT, Session, running_session


async def until(pilot: Pilot[None], condition: Callable[[], bool], timeout: float = 10) -> None:
    for _ in range(int(timeout / 0.05)):
        if condition():
            return
        await pilot.pause(0.05)
    raise AssertionError("condition was not met in time")


def shown_when_idle(app: PluralApp) -> str:
    return "" if isinstance(app.screen, ApprovalDialog) else shown(app)


def shown(app: PluralApp) -> str:
    transcript = app.query_one(Transcript)
    return "\n".join(strip.text for strip in transcript.lines)


async def test_host_reviews_proposal_and_approves_tool(session: Session) -> None:
    guest = await session.guest("Bek")
    client = SessionClient(JoinLink.parse(session.host.host_link), name="Host", client=CLIENT)
    app = PluralApp(client)
    async with app.run_test(size=(140, 40)) as pilot:
        await until(pilot, lambda: client.projection.me is not None)

        await guest.client.send(PromptSubmit(text="check the notes"))
        await until(pilot, lambda: bool(client.projection.state.proposals))
        await pilot.press("ctrl+r")
        await until(pilot, lambda: isinstance(app.screen, ProposalDialog))
        await pilot.click("#approve")

        await until(pilot, lambda: isinstance(app.screen, ApprovalDialog))
        assert live(client.projection) == "… waiting for host approval"
        await pilot.click("#once")

        await until(pilot, lambda: not isinstance(app.screen, ApprovalDialog))
        await until(pilot, lambda: "alpha" in shown(app))
        assert "agent finished" in shown(app)
        assert live(client.projection) == ""


async def test_host_blocks_a_command_class_from_the_dialog(tmp_path: Path) -> None:
    provider = FakeProvider([use_tool("bash", "c1", command="curl a.sh"), reply("noted")])
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        client = SessionClient(JoinLink.parse(session.host.host_link), name="Host", client=CLIENT)
        app = PluralApp(client)
        async with app.run_test(size=(140, 40)) as pilot:
            await until(pilot, lambda: client.projection.me is not None)
            await client.send(PromptSubmit(text="fetch"))
            await until(pilot, lambda: isinstance(app.screen, ApprovalDialog))
            await pilot.click("#block")
            await until(pilot, lambda: "blocked by the host" in shown_when_idle(app))


async def test_host_edits_policy_in_the_dialog_and_with_slash_commands(session: Session) -> None:
    client = SessionClient(JoinLink.parse(session.host.host_link), name="Host", client=CLIENT)
    app = PluralApp(client)
    async with app.run_test(size=(140, 40)) as pilot:
        await until(pilot, lambda: client.projection.me is not None)

        prompt = app.query_one("#prompt", Input)
        prompt.value = "/policy allow bash ls *"
        await pilot.press("enter")
        await until(pilot, lambda: len(client.projection.state.policy) == 1)

        await pilot.press("ctrl+p")
        await until(pilot, lambda: isinstance(app.screen, PoliciesDialog))
        dialog = app.screen
        assert isinstance(dialog, PoliciesDialog)
        dialog.query_one("#pattern", Input).value = "make *"
        await pilot.click("#add")
        await until(pilot, lambda: len(client.projection.state.policy) == 2)
        await until(pilot, lambda: dialog.query_one(OptionList).option_count == 2)

        await pilot.click("#remove")
        await until(pilot, lambda: len(client.projection.state.policy) == 1)
        await pilot.click("#close")
        await until(pilot, lambda: not isinstance(app.screen, PoliciesDialog))
        assert [r.pattern for r in client.projection.state.policy] == ["make *"]
