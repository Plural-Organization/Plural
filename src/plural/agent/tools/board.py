from typing import Final, Literal, Protocol

from pydantic import Field

from plural.agent.tools.base import Tool, ToolArgs, ToolCtx, ToolResult, ToolSpec, TypedTool
from plural.protocol.commands import BoardDraw, BoardErase, BoardMove, BoardOpen
from plural.protocol.models import BOARD_TEXT_CHARS, BoardShape, BoardStroke, BoardView, ToolRisk

# The name the agent's marks carry on the shared board.
AGENT_AUTHOR: Final = "agent"
MAX_MARKS: Final = 60

COORDINATES = (
    "The board is the room's shared drawing surface. A point is (x, y) in board widths: x runs "
    "from 0 at the left to 1 at the right, y from 0 at the top downwards, up to 4; a square "
    "needs the same span on both axes. A screen usually shows y up to about 1.2."
)
COLORS = (
    "#ecebe7 white, #b9b4ff violet, #9fd8ff blue, #8fdca6 green, "
    "#ecc47e yellow, #ff9a9a red, #ff9fc4 pink"
)


class BoardRefused(Exception):
    pass


class BoardDesk(Protocol):
    """The agent's way to the board: it reads the board and asks the session to change it."""

    def view(self) -> tuple[BoardView, dict[str, str]]: ...

    async def apply(self, command: BoardOpen | BoardDraw | BoardMove | BoardErase) -> str: ...


def _span(stroke: BoardStroke) -> str:
    xs = stroke.points[0::2]
    ys = stroke.points[1::2]
    return f"x {min(xs):.3f}..{max(xs):.3f}, y {min(ys):.3f}..{max(ys):.3f}"


def describe(view: BoardView, names: dict[str, str]) -> str:
    if not view.strokes:
        return f"The board is {'open' if view.open else 'closed'} and empty.\n{COORDINATES}"
    lines = [
        f"The board is {'open' if view.open else 'closed'} with {len(view.strokes)} marks, "
        "oldest first:"
    ]
    for stroke in view.strokes:
        who = (
            "you"
            if stroke.author_id == AGENT_AUTHOR
            else names.get(stroke.author_id, stroke.author_id)
        )
        if stroke.kind is BoardShape.TEXT:
            what = f'text "{stroke.text}" at ({stroke.points[0]:.3f}, {stroke.points[1]:.3f})'
        elif stroke.kind in (BoardShape.PEN, BoardShape.ERASE):
            name = "freehand line" if stroke.kind is BoardShape.PEN else "eraser stroke"
            what = f"{name} of {len(stroke.points) // 2} points, {_span(stroke)}"
        elif stroke.kind is BoardShape.IMAGE:
            what = f"picture, {_span(stroke)}"
        else:
            corners = ", ".join(f"{value:.3f}" for value in stroke.points)
            what = f"{stroke.kind.value} with corners ({corners})"
        lines.append(
            f"- {stroke.id}: {what}, color {stroke.color}, width {stroke.width:g}, by {who}"
        )
    return "\n".join([*lines, COORDINATES])


class BoardViewArgs(ToolArgs):
    pass


class BoardViewTool(TypedTool[BoardViewArgs]):
    spec = ToolSpec(
        name="board_view",
        description=(
            "List what is on the room's shared board: every mark with its id, kind, position, "
            "color and who drew it. Look before you change the board. " + COORDINATES
        ),
        risk=ToolRisk.READ,
        args_model=BoardViewArgs,
    )

    def __init__(self, desk: BoardDesk) -> None:
        self._desk = desk

    def subject(self, args: BoardViewArgs) -> str:
        return "the board"

    async def run(self, args: BoardViewArgs, ctx: ToolCtx) -> ToolResult:
        return ToolResult(describe(*self._desk.view()))


class Mark(ToolArgs):
    kind: Literal["pen", "line", "arrow", "rect", "ellipse", "text"] = Field(
        description=(
            "pen: a freehand line through all points; line and arrow: from the first point to "
            "the second, the arrow pointing at the second; rect and ellipse: in the box between "
            "two corners; text: words starting at one point (its top left)"
        )
    )
    points: list[float] = Field(
        description=(
            "x0, y0, x1, y1, … in board widths: one point for text, two for shapes, "
            "two or more for pen"
        ),
        min_length=2,
        max_length=4000,
    )
    text: str | None = Field(
        default=None, max_length=BOARD_TEXT_CHARS, description="The words of a text mark"
    )
    color: str = Field(
        default="#ecebe7",
        pattern=r"^#[0-9a-fA-F]{6}$",
        description=f"Hex color. The board is dark; the room's colors are {COLORS}",
    )
    width: float = Field(
        default=4,
        ge=0.5,
        le=40,
        description=(
            "Line width in thousandths of the board width; a text's size grows with it "
            "(2 small, 4 medium, 9 large)"
        ),
    )


class BoardDrawArgs(ToolArgs):
    marks: list[Mark] = Field(min_length=1, max_length=MAX_MARKS)


class BoardDrawTool(TypedTool[BoardDrawArgs]):
    spec = ToolSpec(
        name="board_draw",
        description=(
            "Draw on the room's shared board, which everyone sees at once: shapes, arrows, "
            "freehand "
            "lines and text, several in one call. It opens the board for everyone if it is closed. "
            "Use it to sketch diagrams, flows and layouts. " + COORDINATES
        ),
        risk=ToolRisk.READ,
        args_model=BoardDrawArgs,
    )

    def __init__(self, desk: BoardDesk) -> None:
        self._desk = desk

    def subject(self, args: BoardDrawArgs) -> str:
        return f"{len(args.marks)} mark{'s' if len(args.marks) != 1 else ''}"

    async def run(self, args: BoardDrawArgs, ctx: ToolCtx) -> ToolResult:
        view, _ = self._desk.view()
        if not view.open:
            await self._desk.apply(BoardOpen(open=True))
        drawn: list[str] = []
        for index, mark in enumerate(args.marks):
            try:
                command = BoardDraw(
                    kind=BoardShape(mark.kind),
                    text=mark.text if mark.kind == "text" else None,
                    color=mark.color,
                    width=mark.width,
                    points=tuple(mark.points),
                )
                drawn.append(await self._desk.apply(command))
            except (BoardRefused, ValueError) as error:
                done = f" Drew {', '.join(drawn)} before it." if drawn else ""
                return ToolResult(f"Mark {index + 1} was refused: {error}.{done}", is_error=True)
        return ToolResult(f"Drew {len(drawn)} marks: {', '.join(drawn)}.")


class BoardMoveArgs(ToolArgs):
    id: str = Field(description="The mark's id from board_view")
    dx: float = Field(
        default=0, ge=-4, le=4, description="Shift right by this much, in board widths"
    )
    dy: float = Field(
        default=0, ge=-4, le=4, description="Shift down by this much, in board widths"
    )
    points: list[float] | None = Field(
        default=None,
        description=(
            "Instead of a shift, the mark's new points, as many as it has now: "
            "a new box for a shape or a picture resizes it"
        ),
    )


class BoardMoveTool(TypedTool[BoardMoveArgs]):
    spec = ToolSpec(
        name="board_move",
        description="Move or resize a mark on the shared board, yours or anyone's. " + COORDINATES,
        risk=ToolRisk.READ,
        args_model=BoardMoveArgs,
    )

    def __init__(self, desk: BoardDesk) -> None:
        self._desk = desk

    def subject(self, args: BoardMoveArgs) -> str:
        return args.id

    async def run(self, args: BoardMoveArgs, ctx: ToolCtx) -> ToolResult:
        view, _ = self._desk.view()
        stroke = next((s for s in view.strokes if s.id == args.id), None)
        if stroke is None:
            return ToolResult(f"No mark {args.id} on the board; call board_view.", is_error=True)
        if args.points is not None:
            points = tuple(args.points)
        else:
            points = tuple(
                min(1.0, max(0.0, value + args.dx))
                if index % 2 == 0
                else min(4.0, max(0.0, value + args.dy))
                for index, value in enumerate(stroke.points)
            )
        try:
            await self._desk.apply(BoardMove(stroke_id=stroke.id, points=points))
        except (BoardRefused, ValueError) as error:
            return ToolResult(f"The move was refused: {error}", is_error=True)
        return ToolResult(f"Moved {stroke.id}.")


class BoardEraseArgs(ToolArgs):
    ids: list[str] = Field(
        min_length=1,
        max_length=MAX_MARKS,
        description="Ids of the marks to remove, from board_view",
    )


class BoardEraseTool(TypedTool[BoardEraseArgs]):
    spec = ToolSpec(
        name="board_erase",
        description="Remove whole marks from the shared board, yours or anyone's.",
        risk=ToolRisk.READ,
        args_model=BoardEraseArgs,
    )

    def __init__(self, desk: BoardDesk) -> None:
        self._desk = desk

    def subject(self, args: BoardEraseArgs) -> str:
        return ", ".join(args.ids)

    async def run(self, args: BoardEraseArgs, ctx: ToolCtx) -> ToolResult:
        gone: list[str] = []
        for stroke_id in args.ids:
            try:
                gone.append(await self._desk.apply(BoardErase(stroke_id=stroke_id)))
            except BoardRefused as error:
                return ToolResult(
                    f"{stroke_id} was refused: {error}. Removed {len(gone)} before it.",
                    is_error=True,
                )
        return ToolResult(f"Removed {len(gone)} marks.")


def board_tools(desk: BoardDesk) -> tuple[Tool, ...]:
    return (BoardViewTool(desk), BoardDrawTool(desk), BoardMoveTool(desk), BoardEraseTool(desk))
