import socket
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import closing
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.request import Request

import pytest

from plural.host import relay_http


@pytest.fixture
def listener() -> Iterator[socket.socket]:
    with closing(socket.socket()) as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        yield server


def _closed_port() -> int:
    with closing(socket.socket()) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _addresses(monkeypatch: pytest.MonkeyPatch, *targets: tuple[int, str, int]) -> None:
    found = [(family, socket.SOCK_STREAM, 6, "", (host, port)) for family, host, port in targets]

    def resolve(
        *_args: object, **_kwargs: object
    ) -> Sequence[tuple[int, int, int, str, tuple[str, int]]]:
        return found

    monkeypatch.setattr(socket, "getaddrinfo", resolve)


def test_a_dead_first_address_does_not_cost_the_whole_timeout(
    monkeypatch: pytest.MonkeyPatch, listener: socket.socket
) -> None:
    live = listener.getsockname()[1]
    # IPv6 is listed first, as the resolver does; the dead one must not decide the wait.
    _addresses(
        monkeypatch, (socket.AF_INET6, "::1", _closed_port()), (socket.AF_INET, "127.0.0.1", live)
    )
    threading.Thread(target=listener.accept, daemon=True).start()
    started = time.monotonic()
    with closing(relay_http._connect(("relay.example", 443), 15)) as sock:  # pyright: ignore[reportPrivateUsage]
        assert sock.getpeername()[1] == live
        assert sock.gettimeout() == 15
    assert time.monotonic() - started < relay_http.ATTEMPT_S


def test_no_answer_from_any_address_is_a_connect_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _addresses(monkeypatch, (socket.AF_INET, "127.0.0.1", _closed_port()))
    with pytest.raises(relay_http.ConnectFailed, match=r"no answer from relay\.example"):
        relay_http._connect(("relay.example", 443), 15)  # pyright: ignore[reportPrivateUsage]


def test_a_name_that_does_not_resolve_is_a_connect_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    with pytest.raises(relay_http.ConnectFailed, match="cannot resolve"):
        relay_http._connect(("relay.example", 443), 15)  # pyright: ignore[reportPrivateUsage]


def test_the_opener_reads_an_answer_through_its_own_connection() -> None:
    class Hello(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("content-length", "2")
            self.end_headers()
            self.wfile.write(b"hi")

        def log_message(self, format: str, *args: object) -> None:
            return

    with HTTPServer(("127.0.0.1", 0), Hello) as server:
        threading.Thread(target=server.handle_request, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        with relay_http.urlopen(Request(url), timeout=5) as response:
            assert response.read() == b"hi"
