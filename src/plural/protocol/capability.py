from datetime import datetime

from plural.protocol.models import Model, Role


class CapabilityClaims(Model):
    room: str
    participant: str
    role: Role
    iat: datetime
    exp: datetime
    jti: str
