import re
from collections.abc import Collection
from urllib.parse import urlsplit

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from plural.protocol.relay import AGENT_PREFIXES

OPEN_PATHS = frozenset({"/healthz"})
# The relay's own routes: a preview's referer never opens them.
_OWN_PREFIXES = ("/teams", "/metrics", "/healthz", "/host/")
_PREVIEW = re.compile(r"/p/[^/]+/[^/]+")


def preview_of(referer: str | None, netloc: str) -> str | None:
    """The preview prefix (`/p/<room>/<secret>`) a request came from on this relay, if any."""
    if not referer:
        return None
    parts = urlsplit(referer)
    match = _PREVIEW.match(parts.path)
    return match.group(0) if match and parts.netloc == netloc else None


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
        # Previews are pages in a browser: their link is the secret, the host checks it.
        path = scope["path"]
        if scope["type"] == "http" and (
            path.startswith("/p/")
            or (
                not path.startswith(_OWN_PREFIXES)
                and preview_of(
                    headers.get(b"referer", b"").decode("latin-1"),
                    headers.get(b"host", b"").decode("latin-1"),
                )
            )
        ):
            return True
        return agent.startswith(AGENT_PREFIXES) or (origin != "" and origin in self._origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        guarded = scope["type"] in ("http", "websocket") and scope["path"] not in OPEN_PATHS
        if not guarded or self._allowed(scope):
            await self._app(scope, receive, send)
        elif scope["type"] == "websocket":
            await receive()
            await send({"type": "websocket.close", "code": 1008})
        else:
            refusal = JSONResponse({"error": "this relay serves Plural clients only"}, 403)
            await refusal(scope, receive, send)
