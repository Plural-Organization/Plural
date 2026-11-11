import asyncio
import json
import os
import shutil
import sys
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast
from uuid import uuid4

import structlog

from plural.host.control import AgentConfig

log = structlog.get_logger(__name__)

MAX_ROOMS = 5
READY_TIMEOUT_S = 60.0
STOP_TIMEOUT_S = 8.0
CONTROL_TIMEOUT_S = 90.0


class RoomError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def host_command() -> list[str]:
    """How to run the host: `PLURAL_HOST_CMD`, else the `plural-host` installed beside us."""
    configured = os.environ.get("PLURAL_HOST_CMD")
    if configured:
        return configured.split()
    beside = Path(sys.executable).parent / "plural-host"
    return [str(beside)] if beside.exists() else [shutil.which("plural-host") or "plural-host"]


class HostControl:
    """The control channel of a host child: requests on its stdin, answers on its stdout."""

    def __init__(self, process: asyncio.subprocess.Process) -> None:
        assert process.stdout is not None
        self._process = process
        self._pending: dict[str, asyncio.Future[dict[str, object]]] = {}
        self.reading = asyncio.create_task(self._read(process.stdout))

    async def _read(self, stream: asyncio.StreamReader) -> None:
        try:
            while line := await stream.readline():
                text = line.decode(errors="replace").strip()
                if not text.startswith("{"):
                    continue
                with suppress(json.JSONDecodeError):
                    parsed: object = json.loads(text)
                    if isinstance(parsed, dict):
                        message = cast("dict[str, object]", parsed)
                        waiting = self._pending.pop(str(message.get("id")), None)
                        if waiting is not None and not waiting.done():
                            waiting.set_result(message)
        finally:
            for waiting in self._pending.values():
                if not waiting.done():
                    waiting.set_exception(RoomError("host_failed", "the host stopped"))
            self._pending.clear()

    async def configure(self, config: AgentConfig) -> str:
        """Switch the host's agent. The key goes down the pipe, never into a log or an answer."""
        payload = config.model_dump(mode="json", exclude_none=True)
        if config.api_key is not None:
            payload["api_key"] = config.api_key.get_secret_value()
        request_id = uuid4().hex
        waiting: asyncio.Future[dict[str, object]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = waiting
        stdin = self._process.stdin
        if stdin is None or stdin.is_closing():
            self._pending.pop(request_id, None)
            raise RoomError("host_failed", "the host stopped")
        message = {"id": request_id, "type": "configure", "config": payload}
        stdin.write(json.dumps(message).encode() + b"\n")
        try:
            await stdin.drain()
            answer = await asyncio.wait_for(waiting, CONTROL_TIMEOUT_S)
        except (OSError, TimeoutError) as error:
            self._pending.pop(request_id, None)
            raise RoomError("agent_failed", "the host did not answer in time") from error
        if answer.get("ok") is not True:
            raise RoomError("agent_failed", str(answer.get("error") or "the agent did not start"))
        return str(answer.get("agent") or "")


@dataclass(slots=True)
class Room:
    room: str
    guest_link: str
    host_link: str
    folder: Path
    title: str | None
    process: asyncio.subprocess.Process
    control: HostControl = field(repr=False)
    agent: str = ""
    watcher: asyncio.Task[None] | None = field(default=None, repr=False)

    def public(self) -> dict[str, object]:
        return {
            "room": self.room,
            "guest_link": self.guest_link,
            "host_link": self.host_link,
            "folder": self.folder.name,
            "title": self.title,
            "agent": self.agent,
        }


class Rooms:
    """Hosts the daemon started: `plural-host host --json` children that end with their stdin."""

    def __init__(self, command: Sequence[str] | None = None, *, limit: int = MAX_ROOMS) -> None:
        self._command = list(command) if command is not None else host_command()
        self._limit = limit
        self._rooms: dict[str, Room] = {}
        self._starting = 0

    def listing(self) -> list[dict[str, object]]:
        return [room.public() for room in self._rooms.values()]

    async def start(
        self,
        folder: Path,
        title: str | None,
        *,
        name: str | None = None,
        agent: AgentConfig | None = None,
        relay: str | None = None,
    ) -> Room:
        if len(self._rooms) + self._starting >= self._limit:
            raise RoomError("too_many_rooms", f"at most {self._limit} rooms at once")
        self._starting += 1
        try:
            return await self._launch(folder, title, name, agent, relay)
        finally:
            self._starting -= 1

    async def _launch(
        self,
        folder: Path,
        title: str | None,
        name: str | None,
        agent: AgentConfig | None,
        relay: str | None,
    ) -> Room:
        arguments = [*self._command, "host", "--json", "--workspace", str(folder)]
        if title:
            arguments += ["--title", title]
        if name:
            arguments += ["--name", name]
        if relay:
            arguments += ["--relay", relay]
        try:
            process = await asyncio.create_subprocess_exec(
                *arguments,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as error:
            raise RoomError("host_missing", f"could not run {self._command[0]}: {error}") from error
        assert process.stdout is not None
        try:
            ready = await asyncio.wait_for(self._read_ready(process), READY_TIMEOUT_S)
        except (TimeoutError, RoomError) as error:
            await self._stop(process)
            if isinstance(error, RoomError):
                raise
            raise RoomError("host_timeout", "the host did not start in time") from error
        room = Room(
            room=str(ready["room"]),
            guest_link=str(ready["guest_link"]),
            host_link=str(ready["host_link"]),
            folder=folder,
            title=title,
            process=process,
            control=HostControl(process),
        )
        if agent is not None:
            try:
                room.agent = await room.control.configure(agent)
            except RoomError:
                await self._stop(process)
                raise
        self._rooms[room.room] = room
        room.watcher = asyncio.create_task(self._forget_when_done(room))
        return room

    @staticmethod
    async def _read_ready(process: asyncio.subprocess.Process) -> dict[str, object]:
        assert process.stdout is not None
        assert process.stderr is not None
        while True:
            line = await process.stdout.readline()
            if not line:
                errors = (await process.stderr.read()).decode(errors="replace").strip()
                raise RoomError("host_failed", errors[-400:] or "the host stopped at start")
            text = line.decode(errors="replace").strip()
            if text.startswith("{"):
                with suppress(json.JSONDecodeError):
                    parsed: object = json.loads(text)
                    if isinstance(parsed, dict):
                        message = cast("dict[str, object]", parsed)
                        if message.get("type") == "ready":
                            return message

    async def _forget_when_done(self, room: Room) -> None:
        await room.process.wait()
        room.control.reading.cancel()
        self._rooms.pop(room.room, None)
        log.info("daemon.room_ended", room=room.room)

    async def set_agent(self, room_id: str, agent: AgentConfig) -> str | None:
        """Switch a room's agent. None if there is no such room."""
        room = self._rooms.get(room_id)
        if room is None:
            return None
        room.agent = await room.control.configure(agent)
        return room.agent

    async def stop(self, room_id: str) -> bool:
        room = self._rooms.get(room_id)
        if room is None:
            return False
        await self._stop(room.process)
        return True

    @staticmethod
    async def _stop(process: asyncio.subprocess.Process) -> None:
        if process.returncode is None and process.stdin is not None:
            with suppress(OSError):
                process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), STOP_TIMEOUT_S)
            except TimeoutError:
                process.kill()
                await process.wait()

    async def close(self) -> None:
        await asyncio.gather(*(self._stop(room.process) for room in list(self._rooms.values())))
