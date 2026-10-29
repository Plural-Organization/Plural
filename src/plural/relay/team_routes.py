import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from pydantic import BaseModel, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from plural.protocol.team import MemberClaims, PresenceCard, SessionList, TeamCreate, TeamJoin
from plural.relay.directory import DirectoryError, TeamDirectory
from plural.relay.limits import Throttle, peer_of
from plural.relay.presence import Presence

MAX_FRAME_BYTES = 8 * 1024
CLOSE_DENIED = 4401
CLOSE_LIMIT = 4429
CLOSE_BAD_FRAME = 4400

Handler = Callable[[Request], Awaitable[Response]]
Signed = Callable[[Request, MemberClaims, bytes], Awaitable[Response]]


def _json(model: BaseModel, status: int = 200) -> JSONResponse:
    return JSONResponse(json.loads(model.model_dump_json()), status_code=status)


def _error(error: DirectoryError) -> JSONResponse:
    return JSONResponse({"error": error.message}, status_code=error.status)


def team_routes(
    directory: TeamDirectory, presence: Presence, *, proxy_hops: int = 0
) -> list[BaseRoute]:
    creations = Throttle(rate=1 / 600, burst=3)
    joins = Throttle(rate=1 / 6, burst=5)

    def peer(request: Request) -> str:
        return peer_of(
            request.headers.get("x-forwarded-for"),
            request.client.host if request.client else None,
            proxy_hops,
        )

    def guarded(handler: Handler) -> Handler:
        async def run(request: Request) -> Response:
            try:
                return await handler(request)
            except DirectoryError as error:
                return _error(error)

        return run

    def signed(handler: Signed) -> Handler:
        async def run(request: Request) -> Response:
            body = await request.body()
            claims = await directory.authenticate(
                str(request.path_params["team"]),
                request.headers.get("authorization"),
                request.method,
                request.url.path,
                body,
            )
            return await handler(request, claims, body)

        return guarded(run)

    async def create(request: Request) -> Response:
        if not creations.allow(peer(request)):
            raise DirectoryError(429, "too many teams from this address, try later")
        try:
            body = TeamCreate.model_validate_json(await request.body())
        except ValidationError as error:
            raise DirectoryError(400, _invalid(error)) from error
        return _json(await directory.create(body), 201)

    async def join(request: Request) -> Response:
        if not joins.allow(peer(request)):
            raise DirectoryError(429, "too many tries from this address, wait a minute")
        try:
            body = TeamJoin.model_validate_json(await request.body())
        except ValidationError as error:
            raise DirectoryError(400, _invalid(error)) from error
        return _json(await directory.join(body), 201)

    async def members(_: Request, claims: MemberClaims, __: bytes) -> Response:
        return _json(await directory.members(claims))

    async def invite(_: Request, claims: MemberClaims, __: bytes) -> Response:
        return _json(await directory.invite(claims), 201)

    async def renew(_: Request, claims: MemberClaims, __: bytes) -> Response:
        return _json(await directory.renew(claims))

    async def remove(request: Request, claims: MemberClaims, __: bytes) -> Response:
        removed = await directory.remove(claims, str(request.path_params["member"]))
        presence.forget_member(claims.team, removed.id)
        return _json(removed)

    async def disband(_: Request, claims: MemberClaims, __: bytes) -> Response:
        await directory.disband(claims)
        presence.forget_team(claims.team)
        return Response(status_code=204)

    async def sessions(_: Request, claims: MemberClaims, __: bytes) -> Response:
        return _json(SessionList(sessions=presence.sessions(claims.team)))

    async def presence_socket(socket: WebSocket) -> None:
        try:
            claims = await directory.authenticate(
                str(socket.path_params["team"]),
                socket.headers.get("authorization"),
                "GET",
                socket.url.path,
                b"",
            )
        except DirectoryError as error:
            await socket.close(code=CLOSE_DENIED, reason=error.message)
            return
        await socket.accept()
        try:
            while True:
                text = await socket.receive_text()
                if len(text) > MAX_FRAME_BYTES:
                    await socket.close(code=CLOSE_BAD_FRAME, reason="frame too large")
                    return
                if not await directory.still_valid(claims):
                    await socket.close(code=CLOSE_DENIED, reason="you are no longer in this team")
                    return
                try:
                    frame = PresenceCard.model_validate_json(text)
                except ValidationError:
                    await socket.close(code=CLOSE_BAD_FRAME, reason="not a session card")
                    return
                if not presence.publish(claims, frame.card, socket, datetime.now(UTC)):
                    await socket.close(code=CLOSE_LIMIT, reason="too many sessions")
                    return
        except WebSocketDisconnect:
            return
        finally:
            presence.drop_held_by(socket)

    return [
        Route("/teams", guarded(create), methods=["POST"]),
        Route("/teams/join", guarded(join), methods=["POST"]),
        Route("/teams/{team}/members", signed(members), methods=["GET"]),
        Route("/teams/{team}/invites", signed(invite), methods=["POST"]),
        Route("/teams/{team}/renew", signed(renew), methods=["POST"]),
        Route("/teams/{team}/members/{member}", signed(remove), methods=["DELETE"]),
        Route("/teams/{team}", signed(disband), methods=["DELETE"]),
        Route("/teams/{team}/sessions", signed(sessions), methods=["GET"]),
        WebSocketRoute("/teams/{team}/presence", presence_socket),
    ]


def _invalid(error: ValidationError) -> str:
    first = error.errors()[0]
    where = ".".join(str(part) for part in first["loc"])
    return f"{where}: {first['msg']}" if where else first["msg"]
