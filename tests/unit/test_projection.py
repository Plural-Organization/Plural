from datetime import UTC, datetime

from plural.client.projection import Projection
from plural.protocol.events import EventRecord, MessageDelta, MessageStarted, RunEnded
from plural.protocol.models import RunEndReason

TS = datetime(2026, 10, 25, tzinfo=UTC)


def test_run_end_discards_unfinished_stream() -> None:
    projection = Projection()
    projection.apply(_record(1, MessageStarted(run_id="run_1", message_id="m1")))
    projection.observe(MessageDelta(message_id="m1", text="half"))
    projection.observe(MessageDelta(message_id="m1", text="hmm", thinking=True))
    assert projection.streaming == {"m1": "half"}
    assert projection.reasoning == 3

    projection.apply(_record(2, RunEnded(run_id="run_1", reason=RunEndReason.ABORTED)))
    assert projection.streaming == {}
    assert projection.reasoning == 0


def _record(seq: int, event: MessageStarted | RunEnded) -> EventRecord:
    return EventRecord(seq=seq, id=f"e{seq}", ts=TS, actor_id=None, event=event)
