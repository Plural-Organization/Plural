import json
import time
from collections.abc import AsyncGenerator, Callable, Collection
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

from plural.protocol.relay import MAX_CALL_BYTES, CallReply, CallRequest
from plural.relay.directory import TeamDirectory, TeamLimits
from plural.relay.gate import ClientGate
from plural.relay.limits import RelayLimits
from plural.relay.presence import Presence
from plural.relay.rooms import CallFailed, Rooms
from plural.relay.team_routes import team_routes

# Long enough for the host to look at what a chat service wants to add and answer.
CALL_TIMEOUT_S = 120.0


def create_app(
    limits: RelayLimits | None = None,
    *,
    proxy_hops: int = 0,
    clock: Callable[[], float] = time.monotonic,
    teams: Path | None = None,
    team_limits: TeamLimits | None = None,
    clients_only: bool = False,
    web_origins: Collection[str] = (),
) -> Starlette:
    rooms = Rooms(limits or RelayLimits(), proxy_hops=proxy_hops, clock=clock)

    async def healthz(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    async def metrics(_: Request) -> JSONResponse:
        return JSONResponse({"rooms": rooms.room_count, "guests": rooms.guest_count})

    async def import_link(request: Request) -> Response:
        """The import link: a chat service posts JSON-RPC here and the room's host answers it."""
        body = bytearray()
        async for chunk in request.stream():
            body += chunk
            if len(body) > MAX_CALL_BYTES:
                return JSONResponse({"error": "too large"}, 413)
        try:
            call = CallRequest(
                token=str(request.path_params["token"]), body=body.decode("utf-8")
            ).model_dump_json()
            raw = await rooms.call(str(request.path_params["room"]), call, timeout_s=CALL_TIMEOUT_S)
            reply = CallReply.model_validate(json.loads(raw))
        except UnicodeDecodeError:
            return JSONResponse({"error": "not text"}, 400)
        except CallFailed as failed:
            return JSONResponse({"error": failed.reason}, failed.status)
        except ValueError:
            return JSONResponse({"error": "the host sent a bad answer"}, 502)
        return Response(reply.body, reply.status, media_type="application/json")

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
            app.router.routes[:0] = team_routes(opened, Presence(), proxy_hops=proxy_hops)
        try:
            yield
        finally:
            for opened in directory:
                await opened.close()

    return Starlette(
        # The team directory answers browsers too. Requests are signed, never sent with cookies,
        # so any page may ask. The ngrok header gets a page past ngrok's browser warning.
        middleware=[
            *([Middleware(ClientGate, origins=web_origins)] if clients_only else []),
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["GET", "POST", "DELETE"],
                allow_headers=["authorization", "content-type", "ngrok-skip-browser-warning"],
                max_age=600,
            ),
        ],
        routes=[
            Route("/healthz", healthz),
            Route("/metrics", metrics),
            Route("/mcp/{room}/{token}", import_link, methods=["POST"]),
            WebSocketRoute("/host/{room}", host_socket),
            WebSocketRoute("/{room}", guest_socket),
        ],
        lifespan=lifespan,
    )
