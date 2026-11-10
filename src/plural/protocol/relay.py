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


class RelayFrame(Model):
    type: Literal["relay.frame"] = "relay.frame"
    conn: str
    data: str


class RelayClosed(Model):
    type: Literal["relay.closed"] = "relay.closed"
    conn: str


RelayMessage = Annotated[RelayOpen | RelayFrame | RelayClosed, Field(discriminator="type")]

RELAY_MESSAGES: TypeAdapter[RelayMessage] = TypeAdapter(RelayMessage)
