"""A room a host on this computer is serving, as it announces itself to local tools.

The host writes one file per room into `<data dir>/running/` while it serves and removes it when
it stops (`storage/running.py`). Local tools such as a chat bridge read them to offer the rooms
without anyone copying a link. The file holds the host link, so it is readable by its owner only,
like the host key next to it.
"""

from datetime import datetime

from plural.protocol.models import Model


class RunningRoom(Model):
    room: str
    host_link: str
    workspace: str
    pid: int
    started_at: datetime
