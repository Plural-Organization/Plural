from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from plural.protocol.models import Model


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
