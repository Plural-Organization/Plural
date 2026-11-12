from datetime import datetime
from typing import Literal

from plural.protocol.models import Model


class EntitlementClaims(Model):
    """What an accounts service signs: this computer key belongs to this account until `exp`."""

    v: Literal[1] = 1
    account: str
    key: str
    iat: datetime
    exp: datetime
