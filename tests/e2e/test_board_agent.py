from pathlib import Path

from pydantic import JsonValue

from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.agent.tools.extra.board import AGENT_AUTHOR, describe
from plural.protocol.commands import BoardDraw, PromptSubmit
from plural.protocol.events import (
    BoardErased,
    BoardMoved,
    BoardOpened,
    BoardStroked,
    RunEnded,
    ToolEnded,
)
from plural.protocol.models import BoardShape, BoardStroke, BoardView
from tests.e2e.support import running_session

BOX: dict[str, JsonValue] = {"kind": "rect", "points": [0.1, 0.1, 0.4, 0.3], "color": "#9fd8ff"}
LABEL: dict[str, JsonValue] = {"kind": "text", "points": [0.12, 0.12], "text": "login"}


async def test_the_agent_draws_moves_and_erases_on_the_board(tmp_path: Path) -> None:
    provider = FakeProvider(
        [
            use_tool("board_draw", "c1", marks=[BOX, LABEL]),
            reply("Drew it."),
        ]
    )
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        await owner.client.send(PromptSubmit(text="sketch a login box"))
        assert (await owner.next(BoardOpened)).by == AGENT_AUTHOR
        box = (await owner.next(BoardStroked)).stroke
        label = (await owner.next(BoardStroked)).stroke
        assert (box.kind, box.author_id, box.points) == (
            BoardShape.RECT,
            AGENT_AUTHOR,
            (0.1, 0.1, 0.4, 0.3),
        )
        assert (label.kind, label.text) == (BoardShape.TEXT, "login")
        await owner.next(RunEnded)

        await owner.client.send(BoardDraw(color="#ffffff", width=2, points=(0.6, 0.6, 0.7, 0.7)))
        mine = (await owner.next(BoardStroked)).stroke
        provider.enqueue(
            use_tool("board_view", "c2"),
            use_tool("board_move", "c3", id=box.id, dx=0.1, dy=0.05),
            use_tool("board_erase", "c4", ids=[mine.id]),
            reply("Tidied up."),
        )
        await owner.client.send(PromptSubmit(text="move the box and remove my line"))
        assert (await owner.next(BoardMoved)).points == (0.2, 0.15, 0.5, 0.35)
        assert (await owner.next(BoardErased)).stroke_id == mine.id
        await owner.next(RunEnded)
        # The board_view result is the last message of the request that follows it.
        seen = provider.requests[3].messages[-1].content
        assert box.id in seen
        assert "login" in seen


async def test_a_refused_mark_is_reported_to_the_agent(tmp_path: Path) -> None:
    provider = FakeProvider(
        [
            use_tool(
                "board_draw", "c1", marks=[{"kind": "rect", "points": [0.1, 0.1]}]
            ),  # one point
            reply("Sorry."),
        ]
    )
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        await owner.client.send(PromptSubmit(text="draw"))
        ended = await owner.next(ToolEnded)
        assert not ended.ok
        assert "two corners" in ended.output


def test_the_board_is_described_with_ids_and_places() -> None:
    view = BoardView(
        open=True,
        strokes=(
            BoardStroke(
                id="st_1",
                author_id="p_alia",
                kind=BoardShape.ARROW,
                color="#ffffff",
                width=2,
                points=(0.1, 0.2, 0.3, 0.4),
            ),
            BoardStroke(
                id="st_2",
                author_id=AGENT_AUTHOR,
                kind=BoardShape.TEXT,
                text="db",
                color="#ffffff",
                width=4,
                points=(0.5, 0.5),
            ),
        ),
    )
    text = describe(view, {"p_alia": "Alia"})
    assert "st_1: arrow with corners (0.100, 0.200, 0.300, 0.400)" in text
    assert "by Alia" in text
    assert 'st_2: text "db" at (0.500, 0.500)' in text
    assert "by you" in text
