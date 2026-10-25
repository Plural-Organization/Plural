from collections.abc import Callable

from textual.pilot import Pilot

from plural.client.presenter import live
from plural.client.reconnect import JoinLink, SessionClient
from plural.protocol.commands import PromptSubmit
from plural.tui.app import PluralApp
from plural.tui.widgets.dialogs import ApprovalDialog, ProposalDialog
from plural.tui.widgets.transcript import Transcript
from tests.e2e.support import CLIENT, Session


async def until(pilot: Pilot[None], condition: Callable[[], bool], timeout: float = 10) -> None:
    for _ in range(int(timeout / 0.05)):
        if condition():
            return
        await pilot.pause(0.05)
    raise AssertionError("condition was not met in time")


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
