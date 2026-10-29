import time
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

from plural.relay.directory import TeamDirectory, TeamLimits
from plural.relay.limits import RelayLimits
from plural.relay.rooms import Rooms
from plural.relay.team_routes import team_routes


def create_app(
    limits: RelayLimits | None = None,
    *,
    proxy_hops: int = 0,
    clock: Callable[[], float] = time.monotonic,
    teams: Path | None = None,
    team_limits: TeamLimits | None = None,
) -> Starlette:
    rooms = Rooms(limits or RelayLimits(), proxy_hops=proxy_hops, clock=clock)

    async def healthz(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    async def metrics(_: Request) -> JSONResponse:
        return JSONResponse({"rooms": rooms.room_count, "guests": rooms.guest_count})

    async def host_socket(socket: WebSocket) -> None:
        await rooms.serve_host(socket, str(socket.path_params["room"]))

    async def guest_socket(socket: WebSocket) -> None:
        await rooms.serve_guest(socket, str(socket.path_params["room"]))

    directory: list[TeamDirectory] = []

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None]:
        if teams is not None:
            opened = await TeamDirectory.open(teams, limits=team_limits)
            directory.append(opened)
            app.router.routes[:0] = team_routes(opened, proxy_hops=proxy_hops)
        try:
            yield
        finally:
            for opened in directory:
                await opened.close()

    return Starlette(
        routes=[
            Route("/healthz", healthz),
            Route("/metrics", metrics),
            WebSocketRoute("/host/{room}", host_socket),
            WebSocketRoute("/{room}", guest_socket),
        ],
        lifespan=lifespan,
    )
