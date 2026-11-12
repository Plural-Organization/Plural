from collections.abc import Collection

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

# What anyone on the computer may ask, with no Origin and no ticket: is a daemon here at all.
OPEN_PATHS = frozenset({"/v1/status"})


class LoopbackGuard:
    """Keeps web pages from using the daemon unless they are the Plural web client.

    Three refusals, each enough on its own: a `Host` that is not the loopback address (a name
    that resolves there later, DNS rebinding), an `Origin` that is not a configured web client,
    and, for everything but `OPEN_PATHS`, no `Origin` at all. Answers carry CORS headers for the
    one origin that asked, and a preflight is answered here. A request that never asked for
    Private Network Access is not turned away for it: browsers differ on sending the header.
    """

    def __init__(self, app: ASGIApp, *, port: int, origins: Collection[str]) -> None:
        self._app = app
        self._hosts = frozenset({f"127.0.0.1:{port}", f"localhost:{port}"})
        self._origins = frozenset(origin.rstrip("/") for origin in origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._app(scope, receive, send)
            return
        if scope["type"] != "http":
            await send({"type": "websocket.close", "code": 1008})
            return
        headers = {
            name.decode("latin-1").lower(): value.decode("latin-1")
            for name, value in scope["headers"]
        }
        if headers.get("host", "") not in self._hosts:
            await _refuse(scope, receive, send, 403, "bad_host", "use 127.0.0.1 or localhost")
            return
        origin = headers.get("origin", "").rstrip("/")
        if origin and origin not in self._origins:
            await _refuse(scope, receive, send, 403, "bad_origin", "this page may not use Plural")
            return
        if not origin and scope["path"] not in OPEN_PATHS:
            await _refuse(scope, receive, send, 403, "no_origin", "only the web client may ask")
            return
        cors = _cors(origin) if origin else []
        if scope["method"] == "OPTIONS":
            await _answer(scope, receive, send, 204, b"", cors)
            return

        async def with_cors(message: dict[str, object]) -> None:
            if message["type"] == "http.response.start":
                raw = message["headers"]
                assert isinstance(raw, list)
                message = {**message, "headers": [*raw, *cors]}
            await send(message)  # type: ignore[arg-type]

        await self._app(scope, receive, with_cors)  # type: ignore[arg-type]


def _cors(origin: str) -> list[tuple[bytes, bytes]]:
    return [
        (b"access-control-allow-origin", origin.encode()),
        (b"vary", b"Origin"),
        (b"access-control-allow-methods", b"GET, POST, PUT, DELETE"),
        (b"access-control-allow-headers", b"authorization, content-type"),
        # Offered for browsers that ask; the check above never depends on the request saying so.
        (b"access-control-allow-private-network", b"true"),
        (b"access-control-max-age", b"60"),
    ]


async def _answer(
    scope: Scope,
    receive: Receive,
    send: Send,
    status: int,
    body: bytes,
    headers: list[tuple[bytes, bytes]],
) -> None:
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


async def _refuse(
    scope: Scope, receive: Receive, send: Send, status: int, code: str, message: str
) -> None:
    await JSONResponse({"error": {"code": code, "message": message}}, status)(scope, receive, send)
