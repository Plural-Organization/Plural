from collections.abc import Collection

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from plural.protocol.relay import AGENT_PREFIXES, MCP_PATH

OPEN_PATHS = frozenset({"/healthz"})


class ClientGate:
    """Lets only Plural clients through: by their User-Agent, or a web client by its origin.

    A browser cannot set its User-Agent, so the web client is told apart by `Origin`. This is a
    filter against scanners and strays, not authentication: the header is easy to send.
    """

    def __init__(self, app: ASGIApp, *, origins: Collection[str] = ()) -> None:
        self._app = app
        self._origins = frozenset(origin.rstrip("/") for origin in origins)

    def _allowed(self, scope: Scope) -> bool:
        headers = {name.lower(): value for name, value in scope["headers"]}
        agent = headers.get(b"user-agent", b"").decode("latin-1").lower()
        origin = headers.get(b"origin", b"").decode("latin-1").rstrip("/")
        return agent.startswith(AGENT_PREFIXES) or (origin != "" and origin in self._origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # The import link is called by a chat service's servers, which are not Plural clients. Its
        # secret is in the path, and the host checks it.
        open_path = scope["path"] in OPEN_PATHS or scope["path"].startswith(MCP_PATH)
        guarded = scope["type"] in ("http", "websocket") and not open_path
        if not guarded or self._allowed(scope):
            await self._app(scope, receive, send)
        elif scope["type"] == "websocket":
            await receive()
            await send({"type": "websocket.close", "code": 1008})
        else:
            refusal = JSONResponse({"error": "this relay serves Plural clients only"}, 403)
            await refusal(scope, receive, send)
