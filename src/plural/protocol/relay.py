from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from plural import __version__
from plural.protocol.models import Model

# What every Plural client calls itself to a relay. A relay may serve only these (and the web
# client by its origin). It keeps scanners and stray scripts out, it is not authentication: anyone
# can send the header.
USER_AGENT = f"plural/{__version__}"
AGENT_PREFIXES = ("plural/", "plural-client")

# A plain HTTPS request a relay hands to a room's host (the import link a chat service calls).
# It travels as a relay frame whose connection id starts with CALL_PREFIX, and the host answers
# with a frame for the same id whose data is a CallReply as JSON.
CALL_PREFIX = "m_"
MCP_PATH = "/mcp/"
MAX_CALL_BYTES = 256 * 1024


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


class CallRequest(Model):
    token: str
    body: str


class CallReply(Model):
    status: int
    body: str = ""


RelayMessage = Annotated[RelayOpen | RelayFrame | RelayClosed, Field(discriminator="type")]

RELAY_MESSAGES: TypeAdapter[RelayMessage] = TypeAdapter(RelayMessage)
