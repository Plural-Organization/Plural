import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ValidationError
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from plural import __version__
from plural.daemon.folders import FolderPickerUnavailable, Folders
from plural.daemon.guard import LoopbackGuard
from plural.daemon.rooms import RoomError, Rooms
from plural.host.account import AccountError, AccountStore
from plural.protocol.entitlement import EntitlementClaims
from plural.security.accounts_key import AccountsKey
from plural.security.entitlement import InvalidEntitlement
from plural.security.replay import ReplayGuard
from plural.security.tokens import b64decode

DEFAULT_PORT = 47831
DEFAULT_ORIGINS = ("https://plrl.host", "https://www.plrl.host")
TICKET_WINDOW = timedelta(minutes=5)


class Problem(Exception):
    def __init__(self, status: int, code: str, message: str, **extra: object) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.extra = extra


class StartRoom(BaseModel):
    folder: str
    title: str | None = None


def linked_account(store: AccountStore) -> tuple[str, str] | None:
    """The account id and email this computer is linked to, or None."""
    try:
        entitlement = store.load()
    except AccountError:
        return None
    if entitlement is None:
        return None
    try:
        body = b64decode(entitlement.certificate.split(".")[0])
        return EntitlementClaims.model_validate_json(body).account, entitlement.email
    except (ValueError, ValidationError):
        return None


class Daemon:
    def __init__(
        self,
        accounts: AccountStore,
        key: AccountsKey,
        folders: Folders,
        rooms: Rooms,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._accounts = accounts
        self._key = key
        self._folders = folders
        self._rooms = rooms
        self._clock = clock
        self._tickets = ReplayGuard(TICKET_WINDOW)

    def authorize(self, request: Request) -> str:
        """Checks the ticket and that it names this computer's account. Returns the email."""
        scheme, _, ticket = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not ticket:
            raise Problem(401, "no_ticket", "sign in on the web client first")
        verifier = self._key.verifier
        if verifier is None:
            raise Problem(503, "key_unavailable", "the accounts key has not been read yet")
        now = self._clock()
        try:
            claims = verifier.ticket(ticket, now=now)
        except InvalidEntitlement as error:
            if error.reason == "forged":
                self._key.suspect()
            raise Problem(401, "bad_ticket", f"the ticket is {error.reason}") from error
        linked = linked_account(self._accounts)
        if linked is None:
            raise Problem(409, "not_linked", "run `plural login` on this computer")
        account, email = linked
        if claims.account != account:
            raise Problem(
                403, "wrong_account", "this computer belongs to another account", linked_email=email
            )
        if not self._tickets.fresh(claims.nonce, now):
            raise Problem(401, "ticket_used", "that ticket was already used")
        return email

    async def status(self, _: Request) -> Response:
        linked = linked_account(self._accounts)
        return JSONResponse({"daemon": True, "version": __version__, "linked": linked is not None})

    async def account(self, request: Request) -> Response:
        return JSONResponse({"email": self.authorize(request)})

    async def pick_folder(self, request: Request) -> Response:
        self.authorize(request)
        try:
            picked = await self._folders.pick()
        except FolderPickerUnavailable as error:
            raise Problem(409, "no_folder_dialog", str(error)) from error
        if picked is None:
            return JSONResponse({"folder": None})
        folder_id, path = picked
        return JSONResponse({"folder": folder_id, "name": path.name})

    async def start_room(self, request: Request) -> Response:
        email = self.authorize(request)
        body = await _body(request, StartRoom)
        folder = self._folders.get(body.folder)
        if folder is None:
            raise Problem(400, "unknown_folder", "choose the folder again")
        title = (body.title or "").strip()[:80] or None
        try:
            room = await self._rooms.start(folder, title, name=email.split("@")[0])
        except RoomError as error:
            raise Problem(409, error.code, str(error)) from error
        return JSONResponse(room.public(), 201)

    async def list_rooms(self, request: Request) -> Response:
        self.authorize(request)
        return JSONResponse({"rooms": self._rooms.listing()})

    async def stop_room(self, request: Request) -> Response:
        self.authorize(request)
        if not await self._rooms.stop(str(request.path_params["room"])):
            raise Problem(404, "no_room", "no such room")
        return Response(status_code=204)


async def _body[T: BaseModel](request: Request, model: type[T]) -> T:
    try:
        return model.model_validate(json.loads(await request.body()))
    except (ValueError, ValidationError) as error:
        raise Problem(400, "bad_request", "the request body is not valid") from error


def _guarded(
    handler: Callable[[Request], Awaitable[Response]],
) -> Callable[[Request], Awaitable[Response]]:
    async def run(request: Request) -> Response:
        try:
            return await handler(request)
        except Problem as problem:
            body: dict[str, Any] = {"code": problem.code, "message": str(problem), **problem.extra}
            return JSONResponse({"error": body}, problem.status)

    return run


def create_app(
    accounts: AccountStore,
    key: AccountsKey,
    *,
    port: int = DEFAULT_PORT,
    origins: tuple[str, ...] = DEFAULT_ORIGINS,
    folders: Folders | None = None,
    rooms: Rooms | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Starlette:
    rooms = rooms or Rooms()
    daemon = Daemon(accounts, key, folders or Folders(), rooms, clock=clock)

    @asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncGenerator[None]:
        key.start()
        try:
            yield
        finally:
            await rooms.close()
            await key.stop()

    return Starlette(
        middleware=[Middleware(LoopbackGuard, port=port, origins=origins)],
        routes=[
            Route("/v1/status", _guarded(daemon.status)),
            Route("/v1/account", _guarded(daemon.account)),
            Route("/v1/folders/pick", _guarded(daemon.pick_folder), methods=["POST"]),
            Route("/v1/rooms", _guarded(daemon.list_rooms)),
            Route("/v1/rooms", _guarded(daemon.start_room), methods=["POST"]),
            Route("/v1/rooms/{room}", _guarded(daemon.stop_room), methods=["DELETE"]),
        ],
        lifespan=lifespan,
    )
