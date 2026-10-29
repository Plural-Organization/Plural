from datetime import UTC, datetime

from plural.core.state import reduce
from plural.protocol.events import BoardStroked, EventRecord
from plural.protocol.models import (
    BOARD_POINTS_LIMIT,
    BOARD_TOTAL_POINTS,
    BoardStroke,
    SessionState,
)


def test_a_full_board_drops_its_oldest_strokes_and_stays_small() -> None:
    state = SessionState()
    last = 2 * BOARD_TOTAL_POINTS // BOARD_POINTS_LIMIT - 1
    points = tuple(0.1234 for _ in range(BOARD_POINTS_LIMIT))
    for seq in range(1, last + 1):
        stroke = BoardStroke(
            id=f"st_{seq}", author_id="p_a", color="#ffffff", width=2, points=points
        )
        record = EventRecord(
            seq=seq,
            id=f"e{seq}",
            ts=datetime.now(UTC),
            actor_id=None,
            event=BoardStroked(stroke=stroke),
        )
        state = reduce(state, record)
    assert sum(len(stroke.points) for stroke in state.board.strokes) <= BOARD_TOTAL_POINTS
    assert state.board.strokes[-1].id == f"st_{last}"
    assert len(state.model_dump_json()) < 2_000_000
