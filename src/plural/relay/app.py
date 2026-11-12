import time
from collections.abc import AsyncGenerator, Callable, Collection
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket

from plural.relay.account_proofs import AccountProofs
from plural.relay.directory import TeamDirectory, TeamLimits
from plural.relay.entitlements import EntitlementWatch
from plural.relay.gate import ClientGate, preview_of
from plural.relay.limits import RelayLimits
from plural.relay.presence import Presence
from plural.relay.rooms import Rooms
from plural.relay.team_routes import team_routes


class OutsidePreviews:
    """Runs a middleware for everything but previews, which answer their own CORS as the app."""

    def __init__(self, app: ASGIApp, *, middleware: Callable[..., ASGIApp], **options: Any) -> None:
        self._app = app
        self._wrapped = middleware(app, **options)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        inner = self._app if str(scope.get("path", "")).startswith("/p/") else self._wrapped
        await inner(scope, receive, send)


PREVIEW_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


def create_app(
    limits: RelayLimits | None = None,
    *,
    proxy_hops: int = 0,
    clock: Callable[[], float] = time.monotonic,
    teams: Path | None = None,
    team_limits: TeamLimits | None = None,
    clients_only: bool = False,
    web_origins: Collection[str] = (),
    accounts_url: str | None = None,
    entitlements: EntitlementWatch | None = None,
) -> Starlette:
    # With an accounts service named, the relay reads each host's certificate and logs what it
    # finds. It turns no one away.
    if entitlements is None and accounts_url:
        entitlements = EntitlementWatch(accounts_url)
    rooms = Rooms(
        limits or RelayLimits(), proxy_hops=proxy_hops, clock=clock, entitlements=entitlements
    )

    async def healthz(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    async def metrics(_: Request) -> JSONResponse:
        counts: dict[str, Any] = {"rooms": rooms.room_count, "guests": rooms.guest_count}
        if entitlements is not None:
            counts["entitlements"] = dict(entitlements.counts)
        return JSONResponse(counts)

    async def host_socket(socket: WebSocket) -> None:
        await rooms.serve_host(socket, str(socket.path_params["room"]))

    async def guest_socket(socket: WebSocket) -> None:
        await rooms.serve_guest(socket, str(socket.path_params["room"]))

    async def preview(request: Request) -> Response:
        params = request.path_params
        return await rooms.serve_preview(request, str(params["room"]), str(params["rest"]))

    async def from_preview(request: Request) -> Response:
        # A preview's page asks for `/assets/app.js` from the relay's root; its own address
        # (the referer) says which preview it belongs to.
        prefix = preview_of(request.headers.get("referer"), request.url.netloc)
        if prefix is None:
            return PlainTextResponse("not found", 404)
        query = f"?{request.url.query}" if request.url.query else ""
        return RedirectResponse(prefix + request.url.path + query, 307)

    directory: list[TeamDirectory] = []

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None]:
        if teams is not None:
            # With an accounts service, a member can be an account rather than a key (ADR 0016).
            watch = entitlements
            proofs = (
                None
                if watch is None
                else AccountProofs(lambda: watch.verifier, suspect=watch.suspect)
            )
            opened = await TeamDirectory.open(teams, limits=team_limits, accounts=proofs)
            directory.append(opened)
            app.router.routes[:0] = team_routes(opened, Presence(), proxy_hops=proxy_hops)
        if entitlements is not None:
            entitlements.start()
        try:
            yield
        finally:
            if entitlements is not None:
                await entitlements.stop()
            for opened in directory:
                await opened.close()

    return Starlette(
        # The team directory answers browsers too. Requests are signed, never sent with cookies,
        # so any page may ask. The ngrok header gets a page past ngrok's browser warning.
        middleware=[
            *([Middleware(ClientGate, origins=web_origins)] if clients_only else []),
            Middleware(
                OutsidePreviews,
                middleware=CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["GET", "POST", "DELETE"],
                allow_headers=["authorization", "content-type", "ngrok-skip-browser-warning"],
                max_age=600,
            ),
        ],
        routes=[
            Route("/healthz", healthz),
            Route("/metrics", metrics),
            WebSocketRoute("/host/{room}", host_socket),
            WebSocketRoute("/{room}", guest_socket),
            Route("/p/{room}/{rest:path}", preview, methods=PREVIEW_METHODS),
            Route("/{rest:path}", from_preview, methods=PREVIEW_METHODS),
        ],
        lifespan=lifespan,
    )
