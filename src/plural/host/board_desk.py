import asyncio
from collections.abc import Callable

from plural.host.inbox import BoardRequest, Inbox
from plural.protocol.commands import BoardDraw, BoardErase, BoardMove, BoardOpen
from plural.protocol.models import BoardView


class InboxDesk:
    """The agent's BoardDesk: each change goes to the session as an inbox message, and the agent
    waits for the session to apply it, so the board changes in one place for everyone."""

    def __init__(self, inbox: Inbox) -> None:
        self._inbox = inbox
        self._view: Callable[[], tuple[BoardView, dict[str, str]]] = lambda: (BoardView(), {})

    def attach(self, view: Callable[[], tuple[BoardView, dict[str, str]]]) -> None:
        self._view = view

    def view(self) -> tuple[BoardView, dict[str, str]]:
        return self._view()

    async def apply(self, command: BoardOpen | BoardDraw | BoardMove | BoardErase) -> str:
        reply: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._inbox.put(BoardRequest(command=command, reply=reply))
        return await reply
