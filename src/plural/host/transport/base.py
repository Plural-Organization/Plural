from typing import TYPE_CHECKING, Protocol

from plural.protocol.envelope import Envelope

if TYPE_CHECKING:
    from plural.host.inbox import Inbox


class Connection(Protocol):
    @property
    def id(self) -> str: ...

    def send(self, envelope: Envelope) -> None: ...

    def close(self, reason: str) -> None: ...


class HostTransport(Protocol):
    async def serve(self, inbox: "Inbox") -> None: ...
