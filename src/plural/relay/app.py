import time
from collections.abc import Callable

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

from plural.relay.limits import RelayLimits
from plural.relay.rooms import Rooms


def create_app(
    limits: RelayLimits | None = None,
    *,
    proxy_hops: int = 0,
    clock: Callable[[], float] = time.monotonic,
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

    return Starlette(
        routes=[
            Route("/healthz", healthz),
            Route("/metrics", metrics),
            WebSocketRoute("/host/{room}", host_socket),
            WebSocketRoute("/{room}", guest_socket),
        ]
    )
