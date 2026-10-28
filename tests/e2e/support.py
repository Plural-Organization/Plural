import asyncio
import socket
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn

from plural.agent.providers.base import LLMProvider
from plural.client.connection import CommandRejected
from plural.client.reconnect import JoinLink, SessionClient
from plural.host.bootstrap import Host, build_host
from plural.host.config import HostSettings
from plural.protocol.commands import ClientInfo
from plural.protocol.envelope import ErrorCode
from plural.protocol.events import Event, SessionWelcome
from plural.protocol.models import Role
from plural.relay.app import create_app

CLIENT = ClientInfo(kind="test", version="0")
ROOM = "r_e2e"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def refusal(client: SessionClient) -> ErrorCode:
    try:
        async for _ in client.events():
            raise AssertionError("client was admitted")
    except CommandRejected as error:
        return error.error.code
    raise AssertionError("stream ended without a refusal")


class Watcher:
    def __init__(self, client: SessionClient) -> None:
        self.client = client
        self.events: list[Event] = []
        self._cursor = 0
        self._task = asyncio.create_task(self._pump())

    async def _pump(self) -> None:
        async for event in self.client.events():
            self.events.append(event)

    async def next[E: Event](self, kind: type[E], timeout: float = 10) -> E:
        async with asyncio.timeout(timeout):
            while True:
                while self._cursor < len(self.events):
                    event = self.events[self._cursor]
                    self._cursor += 1
                    if isinstance(event, kind):
                        return event
                await asyncio.sleep(0.01)

    async def stop(self) -> None:
        self._task.cancel()
        with suppress(asyncio.CancelledError, CommandRejected):
            await self._task


class RelayServer:
    def __init__(self, port: int | None = None) -> None:
        self.port = port or free_port()
        self._server: uvicorn.Server | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}"

    @property
    def running(self) -> bool:
        return self._server is not None

    async def start(self) -> None:
        server = uvicorn.Server(
            uvicorn.Config(create_app(), host="127.0.0.1", port=self.port, log_level="warning")
        )
        self._task = asyncio.create_task(server.serve())
        self._server = server
        async with asyncio.timeout(10):
            while not server.started:
                await asyncio.sleep(0.01)

    async def stop(self) -> None:
        if self._server is None or self._task is None:
            return
        self._server.should_exit = True
        await self._task
        self._server = None
        self._task = None


@dataclass(slots=True)
class Session:
    host: Host
    watchers: list[Watcher]
    relay: RelayServer | None = None

    async def watch(self, link: str, name: str) -> Watcher:
        watcher = Watcher(SessionClient(JoinLink.parse(link), name=name, client=CLIENT))
        self.watchers.append(watcher)
        await watcher.next(SessionWelcome)
        return watcher

    async def owner(self) -> Watcher:
        return await self.watch(self.host.host_link, "Host")

    async def guest(self, name: str, role: Role = Role.PARTICIPANT) -> Watcher:
        return await self.watch(self.host.invites.create(role, 600).link, name)


@asynccontextmanager
async def running_session(
    tmp_path: Path,
    *,
    relayed: bool,
    provider: LLMProvider,
    overrides: dict[str, Any] | None = None,
) -> AsyncGenerator[Session]:
    workspace = tmp_path / "ws"
    workspace.mkdir(exist_ok=True)
    (workspace / "notes.txt").write_text("alpha\nbeta\n")
    relay: RelayServer | None = None
    relay_url: str | None = None
    if relayed:
        relay = RelayServer()
        await relay.start()
        relay_url = relay.url
    options: dict[str, Any] = {"provider": "fake", **(overrides or {})}
    settings = HostSettings(
        workspace=workspace,
        data_dir=tmp_path / "data",
        room=ROOM,
        port=free_port(),
        relay_url=relay_url,
        approval_timeout_s=30,
        **options,
    )
    host = await build_host(settings, provider=provider)
    serving = asyncio.create_task(host.serve())
    session = Session(host=host, watchers=[], relay=relay)
    try:
        yield session
    finally:
        for watcher in session.watchers:
            await watcher.stop()
        serving.cancel()
        with suppress(asyncio.CancelledError):
            await serving
        await host.close()
        if relay is not None:
            await relay.stop()
