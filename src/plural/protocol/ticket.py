from datetime import datetime
from typing import Literal

from plural.protocol.models import Model


class TicketClaims(Model):
    """What an accounts service signs for a browser session: this session belongs to `account`.

    `aud` names the receiver: the program on the person's computer (`daemon`, ADR 0014) or a team
    directory (`teams`, ADR 0016). Each accepts only its own, once, for under a minute. A ticket
    carries no host key, and a certificate carries no `aud`, so one never parses as the other.
    """

    v: Literal[1] = 1
    aud: Literal["daemon", "teams"] = "daemon"
    account: str
    nonce: str
    iat: datetime
    exp: datetime
