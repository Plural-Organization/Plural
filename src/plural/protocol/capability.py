from datetime import datetime

from plural.protocol.models import Model, Role


class CapabilityClaims(Model):
    room: str
    participant: str
    role: Role
    iat: datetime
    exp: datetime
    jti: str


class SuccessionClaims(Model):
    """The old host's word that another key now holds its room, for the relay and for the new host.

    It names the room and both keys, so it cannot be moved to another room or another successor, and
    it lapses soon: a handover that did not finish must not be completable later, after the old host
    has gone on."""

    room: str
    from_key: str
    to_key: str
    # The last event of the session the old host handed over. The new host's log ends here.
    last_seq: int
    iat: datetime
    exp: datetime
