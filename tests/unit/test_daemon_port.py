import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from plural.daemon.port import PortState, port_state


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def serve(body: bytes) -> HTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_a_free_port_is_free() -> None:
    assert port_state(free_port()) is PortState.FREE


def test_a_daemon_on_the_port_is_recognised() -> None:
    server = serve(json.dumps({"daemon": True, "version": "1"}).encode())
    try:
        assert port_state(server.server_port) is PortState.DAEMON
    finally:
        server.shutdown()


def test_something_else_on_the_port_is_busy() -> None:
    server = serve(b"<html>not plural</html>")
    try:
        assert port_state(server.server_port) is PortState.BUSY
    finally:
        server.shutdown()
