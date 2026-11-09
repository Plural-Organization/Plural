from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from plural import __version__
from plural.protocol.models import Model

# What every Plural client calls itself to a relay. A relay may serve only these (and the web
# client by its origin). It keeps scanners and stray scripts out, it is not authentication: anyone
# can send the header.
USER_AGENT = f"plural/{__version__}"
AGENT_PREFIXES = ("plural/", "plural-client")


class RelayOpen(Model):
    type: Literal["relay.open"] = "relay.open"
    room: str
    public_key: str
    proof: str
    # A certificate from an accounts service, for a relay that asks hosts to belong to an account.
    entitlement: str | None = None


class RelayFrame(Model):
    type: Literal["relay.frame"] = "relay.frame"
    conn: str
    data: str


class RelayClosed(Model):
    type: Literal["relay.closed"] = "relay.closed"
    conn: str


class RelayHttpRequest(Model):
    """A browser's request for a host's preview, which the relay hands to the room's host."""

    type: Literal["relay.http"] = "relay.http"
    id: str
    method: str
    path: str
    headers: list[tuple[str, str]] = Field(default_factory=list[tuple[str, str]])
    body: str = ""


class RelayHttpReply(Model):
    """The host's answer in parts: the first carries the status and headers, the last says `end`."""

    type: Literal["relay.http.reply"] = "relay.http.reply"
    id: str
    status: int = 0
    headers: list[tuple[str, str]] = Field(default_factory=list[tuple[str, str]])
    body: str = ""
    end: bool = False


RelayMessage = Annotated[
    RelayOpen | RelayFrame | RelayClosed | RelayHttpRequest | RelayHttpReply,
    Field(discriminator="type"),
]

RELAY_MESSAGES: TypeAdapter[RelayMessage] = TypeAdapter(RelayMessage)
