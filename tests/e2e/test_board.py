import pytest

from plural.client.connection import CommandRejected
from plural.protocol.commands import BoardClear, BoardDraw, BoardErase, BoardOpen, CursorSet
from plural.protocol.envelope import ErrorCode
from plural.protocol.events import (
    BoardCleared,
    BoardErased,
    BoardOpened,
    BoardStroked,
    ParticipantCursor,
    SessionSnapshot,
)
from plural.protocol.models import BoardCursor, BoardShape, Role
from tests.e2e.support import Session

LINE = BoardDraw(color="#b9b4ff", width=3, points=(0.1, 0.1, 0.5, 0.4, 0.9, 0.2))


async def test_opening_the_board_shows_it_to_everyone_each_time(session: Session) -> None:
    owner = await session.owner()
    guest = await session.guest("Alia")
    await guest.client.send(BoardOpen(open=True))
    opened = await owner.next(BoardOpened)
    assert (opened.open, opened.by) == (True, guest.client.projection.me_id)
    await guest.client.send(BoardOpen(open=True))
    await owner.next(BoardOpened)
    await guest.client.send(BoardOpen(open=False))
    await owner.next(BoardOpened)
    await guest.client.send(BoardOpen(open=False))
    await guest.client.send(BoardOpen(open=True))
    await owner.next(BoardOpened)
    assert [e.open for e in owner.events if isinstance(e, BoardOpened)] == [True, True, False, True]


async def test_shapes_and_text_keep_what_they_need(session: Session) -> None:
    owner = await session.owner()
    guest = await session.guest("Alia")
    box = BoardDraw(kind=BoardShape.RECT, color="#ffffff", width=2, points=(0.1, 0.1, 0.4, 0.3))
    await guest.client.send(box)
    assert (await owner.next(BoardStroked)).stroke.kind is BoardShape.RECT
    note = BoardDraw(
        kind=BoardShape.TEXT, text="login", color="#ffffff", width=4, points=(0.5, 0.5)
    )
    await guest.client.send(note)
    assert (await owner.next(BoardStroked)).stroke.text == "login"
    for wrong in (
        BoardDraw(
            kind=BoardShape.RECT, color="#ffffff", width=2, points=(0.1, 0.1, 0.2, 0.2, 0.3, 0.3)
        ),
        BoardDraw(kind=BoardShape.TEXT, color="#ffffff", width=2, points=(0.1, 0.1)),
        BoardDraw(text="stray", color="#ffffff", width=2, points=(0.1, 0.1, 0.2, 0.2)),
    ):
        with pytest.raises(CommandRejected) as rejected:
            await guest.client.send(wrong)
        assert rejected.value.error.code is ErrorCode.INVALID


async def test_a_stroke_is_kept_for_people_who_come_later(session: Session) -> None:
    owner = await session.owner()
    guest = await session.guest("Alia")
    await guest.client.send(LINE)
    stroke = (await owner.next(BoardStroked)).stroke
    assert stroke.author_id == guest.client.projection.me_id
    assert stroke.points == LINE.points
    late = await session.guest("Bek")
    snapshot = next(e for e in late.events if isinstance(e, SessionSnapshot))
    assert [s.id for s in snapshot.state.board.strokes] == [stroke.id]


async def test_only_the_author_or_the_host_erases_a_stroke(session: Session) -> None:
    owner = await session.owner()
    alia = await session.guest("Alia")
    bek = await session.guest("Bek")
    await alia.client.send(LINE)
    stroke = (await owner.next(BoardStroked)).stroke
    with pytest.raises(CommandRejected) as rejected:
        await bek.client.send(BoardErase(stroke_id=stroke.id))
    assert rejected.value.error.code is ErrorCode.FORBIDDEN
    await alia.client.send(BoardErase(stroke_id=stroke.id))
    assert (await owner.next(BoardErased)).stroke_id == stroke.id


async def test_the_host_clears_the_board(session: Session) -> None:
    owner = await session.owner()
    guest = await session.guest("Alia")
    await guest.client.send(LINE)
    await owner.next(BoardStroked)
    with pytest.raises(CommandRejected):
        await guest.client.send(BoardClear())
    await owner.client.send(BoardClear())
    assert (await owner.next(BoardCleared)).by == owner.client.projection.me_id


async def test_a_stroke_with_half_a_point_is_refused(session: Session) -> None:
    guest = await session.guest("Alia")
    with pytest.raises(CommandRejected) as rejected:
        await guest.client.send(BoardDraw(color="#ffffff", width=2, points=(0.1, 0.2, 0.3)))
    assert rejected.value.error.code is ErrorCode.INVALID


async def test_viewers_point_but_do_not_draw(session: Session) -> None:
    owner = await session.owner()
    viewer = await session.guest("Eve", Role.VIEWER)
    await viewer.client.send(CursorSet(cursor=BoardCursor(x=0.5, y=0.5)))
    cursor = await owner.next(ParticipantCursor)
    assert cursor.cursor == BoardCursor(x=0.5, y=0.5)
    with pytest.raises(CommandRejected) as rejected:
        await viewer.client.send(LINE)
    assert rejected.value.error.code is ErrorCode.FORBIDDEN


async def test_leaving_hides_the_cursor(session: Session) -> None:
    owner = await session.owner()
    guest = await session.guest("Alia")
    await guest.client.send(
        CursorSet(cursor=BoardCursor(x=0.2, y=0.3, ink=True, color="#ffffff", width=2))
    )
    await owner.next(ParticipantCursor)
    await guest.stop()
    assert (await owner.next(ParticipantCursor)).cursor is None


async def test_points_are_rounded_to_keep_the_log_small(session: Session) -> None:
    owner = await session.owner()
    guest = await session.guest("Alia")
    await guest.client.send(
        BoardDraw(color="#ffffff", width=2, points=(0.123456789, 0.5, 0.987654321, 0.25))
    )
    assert (await owner.next(BoardStroked)).stroke.points == (0.1235, 0.5, 0.9877, 0.25)
