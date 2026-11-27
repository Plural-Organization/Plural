from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from plural.bridge.model import Answer, Incoming, Notice, Place, Pressed


class PlatformError(Exception):
    """A chat service refused or failed. The bridge reports it and may try again."""


class AuthError(PlatformError):
    """The credentials are wrong or were revoked. Trying again will not help."""


@dataclass(frozen=True, slots=True)
class Links:
    """Where a person goes to meet the bot, known once it is connected.

    `open` opens a private chat with the bot. It may hold `{code}`: then the service starts the
    pairing by itself and nobody types the code. `invite` adds the bot to a group or a server.
    """

    open: str = ""
    invite: str = ""

    @property
    def autopair(self) -> bool:
        return "{code}" in self.open


class ChatPlatform(Protocol):
    """A chat service the bridge talks through."""

    name: str

    @property
    def identity(self) -> str:
        """How people find the bot on this service, for example `@my_bot`. Known after start."""
        ...

    @property
    def links(self) -> Links:
        """Links to the bot for the settings screens. Known after start."""
        ...

    async def start(self) -> None:
        """Connects and learns who the bot is. Raises `AuthError` when the credentials are wrong."""
        ...

    def incoming(self) -> AsyncIterator[Incoming]: ...

    async def show(
        self,
        place: Place,
        key: str,
        view: Answer | Notice,
        *,
        final: bool = True,
        reply_to: str | None = None,
    ) -> None:
        """Shows a view under a key: the first call sends a message, later calls with the same
        key and place change it. A platform may skip views that are not final when they come
        faster than it can show them, but never a final one."""
        ...

    async def answer(self, pressed: Pressed, text: str = "", *, alert: bool = False) -> None:
        """Acknowledges a button, with a short text for the person who pressed it."""
        ...

    async def close(self) -> None: ...
