from datetime import datetime
from typing import Literal

from plural.protocol.models import Model


class TicketClaims(Model):
    """What an accounts service signs for a browser session: this session belongs to `account`.

    A program on the person's computer accepts it once, for under a minute. It carries no host
    key, and a certificate carries no `aud`, so one never parses as the other.
    """

    v: Literal[1] = 1
    aud: Literal["daemon"] = "daemon"
    account: str
    nonce: str
    iat: datetime
    exp: datetime
