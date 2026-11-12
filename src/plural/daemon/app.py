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
from plural.agent_setup import AgentSetup, AgentSetupError, Choice
from plural.daemon.folders import FolderPickerUnavailable, Folders
from plural.daemon.guard import LoopbackGuard
from plural.daemon.rooms import RoomError, Rooms
from plural.daemon.terminal import SystemTerminal, Terminal, TerminalUnavailable
from plural.host import extras, tools
from plural.host.account import AccountError, AccountStore
from plural.host.config import DEFAULT_RELAY_URL, HostSettings
from plural.host.team import TeamError, TeamProfile, TeamStore, account_teams
from plural.protocol.entitlement import EntitlementClaims
from plural.security.accounts_key import AccountsKey
from plural.security.entitlement import InvalidEntitlement
from plural.security.identity import Identity
from plural.security.replay import ReplayGuard
from plural.security.tokens import b64decode

DEFAULT_PORT = 47831
DEFAULT_ORIGINS = ("https://plrl.host", "https://www.plrl.host")
TICKET_WINDOW = timedelta(minutes=5)


TeamFetch = Callable[[str, Identity, str, Callable[[bytes], str]], Awaitable[list[TeamProfile]]]


class Problem(Exception):
    def __init__(self, status: int, code: str, message: str, **extra: object) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.extra = extra


class StartRoom(BaseModel):
    folder: str
    title: str | None = None
    agent: Choice | None = None  # the provider and model; a key is never sent, the daemon has it
    # None: the relay this computer uses. "": the Plural relay. An address: that relay, from now on.
    relay: str | None = None
    # One of this computer's teams to show the room to; the room then uses that team's relay.
    team: str | None = None


class SetAgent(BaseModel):
    agent: Choice


class AgentKey(BaseModel):
    preset: str
    key: str


class AgentTest(BaseModel):
    choice: Choice
    key: str | None = None  # a key typed but not saved yet


class AgentInstall(BaseModel):
    tool: tools.Tool | None = None
    extra: extras.Extra | None = None


class AgentSignIn(BaseModel):
    tool: tools.Tool


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
        agent: AgentSetup,
        terminal: Terminal,
        teams: TeamStore,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        fetch_teams: TeamFetch = account_teams,
        team_relay: str = DEFAULT_RELAY_URL,
    ) -> None:
        self._teams = teams
        self._fetch_teams = fetch_teams
        self._team_relay = team_relay
        self._agent = agent
        self._terminal = terminal
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
            claims = verifier.ticket(ticket, now=now, audience="daemon")
        except InvalidEntitlement as error:
            if error.reason == "forged":
                self._key.suspect()
            raise Problem(
                401, "bad_ticket", f"the ticket is {error.reason}", reason=error.reason
            ) from error
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
            config = self._agent.config(body.agent or self._agent.store.current())
        except AgentSetupError as error:
            raise Problem(409, "agent_not_ready", str(error)) from error
        team = self._team(body.team)
        # A team room goes through its team's relay, so a relay named here does not apply.
        relay = None if team is not None else (self._relay(body.relay) or None)
        try:
            room = await self._rooms.start(
                folder, title, name=email.split("@")[0], agent=config, relay=relay, team=team
            )
        except RoomError as error:
            raise Problem(409, error.code, str(error)) from error
        return JSONResponse(room.public(), 201)

    def _relay(self, asked: str | None) -> str:
        """The relay for a new room. One the page names becomes this computer's relay."""
        store = self._agent.store
        if asked is None:
            return store.relay()
        try:
            if asked.strip() != store.relay():
                store.set_relay(asked)
        except AgentSetupError as error:
            raise Problem(400, "bad_relay", str(error)) from error
        return store.relay()

    def _team(self, asked: str | None) -> str | None:
        if asked is None:
            return None
        try:
            known = {profile.team_id for profile in self._teams.profiles()}
        except TeamError as error:
            raise Problem(409, "teams_damaged", str(error)) from error
        if asked not in known:
            raise Problem(400, "unknown_team", "this computer is not in that team")
        return asked

    async def list_teams(self, request: Request) -> Response:
        """This computer's teams, after asking the relays for the account's (ADR 0016)."""
        self.authorize(request)
        errors: list[str] = []
        try:
            linked = self._accounts.load()
        except AccountError:
            linked = None
        if linked is not None:
            identity = self._teams.identity()
            prove = self._accounts.signer().prove
            try:
                relays = [self._team_relay, *(p.relay for p in self._teams.profiles())]
            except TeamError as error:
                raise Problem(409, "teams_damaged", str(error)) from error
            for relay in dict.fromkeys(relays):
                try:
                    found = await self._fetch_teams(relay, identity, linked.certificate, prove)
                except TeamError as error:
                    errors.append(f"{relay}: {error}")
                    continue
                for profile in found:
                    self._teams.keep(profile)
        teams = [
            {
                "id": profile.team_id,
                "name": profile.team_name,
                "role": profile.member.role.value,
                "relay": profile.relay,
            }
            for profile in self._teams.profiles()
        ]
        return JSONResponse({"teams": teams, "errors": errors})

    async def settings(self, request: Request) -> Response:
        self.authorize(request)
        return JSONResponse({"relay": self._agent.store.relay() or None})

    async def set_room_agent(self, request: Request) -> Response:
        self.authorize(request)
        body = await _body(request, SetAgent)
        try:
            config = self._agent.config(body.agent)
        except AgentSetupError as error:
            raise Problem(409, "agent_not_ready", str(error)) from error
        try:
            label = await self._rooms.set_agent(str(request.path_params["room"]), config)
        except RoomError as error:
            raise Problem(409, error.code, str(error)) from error
        if label is None:
            raise Problem(404, "no_room", "no such room")
        return JSONResponse({"agent": label})

    async def agent_catalog(self, request: Request) -> Response:
        self.authorize(request)
        catalog = await self._agent.catalog()
        return Response(catalog.model_dump_json(by_alias=True), media_type="application/json")

    async def save_agent(self, request: Request) -> Response:
        self.authorize(request)
        body = await _body(request, SetAgent)
        try:
            self._agent.use(body.agent)
        except AgentSetupError as error:
            raise Problem(409, "agent_not_ready", str(error)) from error
        return Response(status_code=204)

    async def save_agent_key(self, request: Request) -> Response:
        self.authorize(request)
        body = await _body(request, AgentKey)
        try:
            self._agent.set_key(body.preset, body.key)
        except AgentSetupError as error:
            raise Problem(400, "bad_key", str(error)) from error
        return Response(status_code=204)

    async def forget_agent_key(self, request: Request) -> Response:
        self.authorize(request)
        try:
            self._agent.clear_key(str(request.path_params["preset"]))
        except AgentSetupError as error:
            raise Problem(404, "no_provider", str(error)) from error
        return Response(status_code=204)

    async def test_agent(self, request: Request) -> Response:
        self.authorize(request)
        body = await _body(request, AgentTest)
        try:
            message = await self._agent.test(body.choice, body.key)
        except AgentSetupError as error:
            raise Problem(409, "agent_failed", str(error)) from error
        return JSONResponse({"message": message})

    async def install_agent_part(self, request: Request) -> Response:
        self.authorize(request)
        body = await _body(request, AgentInstall)
        try:
            if body.tool is not None:
                await tools.install(body.tool)
            elif body.extra is not None:
                await extras.install(body.extra)
            else:
                raise Problem(400, "bad_request", "say which tool or extra to install")
        except (tools.ToolInstallError, extras.InstallError) as error:
            raise Problem(502, "install_failed", str(error)) from error
        return Response(status_code=204)

    async def sign_in_agent(self, request: Request) -> Response:
        self.authorize(request)
        body = await _body(request, AgentSignIn)
        spec = next(spec for spec in tools.SPECS if spec.id == body.tool)
        try:
            await self._terminal.run(spec.login)
        except TerminalUnavailable as error:
            raise Problem(409, "no_terminal", str(error), command=spec.login) from error
        return JSONResponse({"command": spec.login})

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
    agent: AgentSetup | None = None,
    terminal: Terminal | None = None,
    teams: TeamStore | None = None,
    fetch_teams: TeamFetch = account_teams,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Starlette:
    rooms = rooms or Rooms()
    state = HostSettings().state_dir
    agent = agent or AgentSetup(state)
    daemon = Daemon(
        accounts,
        key,
        folders or Folders(),
        rooms,
        agent,
        terminal or SystemTerminal(),
        teams or TeamStore(state),
        clock=clock,
        fetch_teams=fetch_teams,
    )

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
            Route("/v1/rooms/{room}/agent", _guarded(daemon.set_room_agent), methods=["PUT"]),
            Route("/v1/settings", _guarded(daemon.settings)),
            Route("/v1/teams", _guarded(daemon.list_teams)),
            Route("/v1/agent", _guarded(daemon.agent_catalog)),
            Route("/v1/agent", _guarded(daemon.save_agent), methods=["PUT"]),
            Route("/v1/agent/key", _guarded(daemon.save_agent_key), methods=["PUT"]),
            Route("/v1/agent/key/{preset}", _guarded(daemon.forget_agent_key), methods=["DELETE"]),
            Route("/v1/agent/test", _guarded(daemon.test_agent), methods=["POST"]),
            Route("/v1/agent/install", _guarded(daemon.install_agent_part), methods=["POST"]),
            Route("/v1/agent/sign-in", _guarded(daemon.sign_in_agent), methods=["POST"]),
        ],
        lifespan=lifespan,
    )
