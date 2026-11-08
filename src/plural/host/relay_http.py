"""HTTP to the relay that gives up on a dead address in seconds, not in the request timeout.

`urlopen` tries each address of a name in turn and waits the whole timeout on each. A machine
whose IPv6 route hangs (a VPN, a NAT64 network) then waits 15 s on the first address before the
IPv4 one that works is tried.
"""

import socket
import ssl
import time
from http.client import HTTPConnection, HTTPSConnection
from typing import Any
from urllib.request import HTTPHandler, HTTPSHandler, OpenerDirector, Request, build_opener

CONNECT_BUDGET_S = 6.0
ATTEMPT_S = 3.0


class ConnectFailed(OSError):
    """No address answered, so nothing was sent and the request may be made again."""


def _connect(address: tuple[str, int], timeout: float | None = None, *_: Any) -> socket.socket:
    host, port = address
    deadline = time.monotonic() + CONNECT_BUDGET_S
    try:
        found = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as error:
        raise ConnectFailed(f"cannot resolve {host}") from error
    # IPv4 first: the broken route is the IPv6 one far more often than the other way round.
    last: OSError | None = None
    for family, kind, proto, _canonical, target in sorted(
        found, key=lambda info: info[0] != socket.AF_INET
    ):
        left = deadline - time.monotonic()
        if left <= 0:
            break
        sock = socket.socket(family, kind, proto)
        sock.settimeout(min(ATTEMPT_S, left))
        try:
            sock.connect(target)
        except OSError as error:
            sock.close()
            last = error
            continue
        sock.settimeout(timeout)
        return sock
    raise ConnectFailed(f"no answer from {host} in {CONNECT_BUDGET_S:g} s") from last


class _Http(HTTPConnection):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._create_connection = _connect


class _Https(HTTPSConnection):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._create_connection = _connect


class _HttpHandler(HTTPHandler):
    def http_open(self, req: Request) -> Any:
        return self.do_open(_Http, req)


class _HttpsHandler(HTTPSHandler):
    def __init__(self) -> None:
        self._tls = ssl.create_default_context()
        super().__init__(context=self._tls)

    def https_open(self, req: Request) -> Any:
        return self.do_open(_Https, req, context=self._tls)


_OPENER: OpenerDirector = build_opener(_HttpHandler, _HttpsHandler)


def urlopen(request: Request, *, timeout: float) -> Any:
    return _OPENER.open(request, timeout=timeout)
