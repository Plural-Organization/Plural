from pathlib import Path

from tests.doubles import FakeProvider, reply, use_tool
from tests.loop_support import StubGate, collect, make_loop, turn

from plural.agent.loop.events import RunEnd
from plural.agent.loop.loop import NUDGE, promises
from plural.protocol.models import RunEndReason


def test_a_short_announcement_is_a_promise_and_a_report_is_not() -> None:
    assert promises("I'll inspect `pages.py` and how pagination is calculated.")
    assert promises("Found the module. Next I will run the tests.")
    assert promises("I’m waiting on the workspace inspection results before making changes.")
    assert not promises("Fixed the off-by-one in `pages.py`; the tests pass.")
    assert not promises("")
    long_report = "Done. " + "The change keeps every caller working. " * 30 + "I'll stop here."
    assert not promises(long_report)


async def test_a_run_that_stops_at_a_promise_is_reminded_and_goes_on(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("alpha\n")
    provider = FakeProvider(
        [
            reply("I'll read a.txt now."),
            use_tool("read", "c1", path="a.txt"),
            reply("a.txt says alpha."),
        ]
    )
    loop = make_loop(tmp_path, provider, StubGate())
    events = await collect(loop, turn("what is in a.txt?"))

    assert [e for e in events if isinstance(e, RunEnd)][-1].reason is RunEndReason.STOP
    second = provider.requests[1].messages[-1]
    assert second.role == "user"
    assert second.content == NUDGE
    assert len(provider.requests) == 3


async def test_reminders_stop_after_two(tmp_path: Path) -> None:
    provider = FakeProvider([reply("I'll look."), reply("I'll look."), reply("I'll look.")])
    loop = make_loop(tmp_path, provider, StubGate())
    await collect(loop, turn("go"))
    assert len(provider.requests) == 3
