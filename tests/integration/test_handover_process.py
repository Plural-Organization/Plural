"""A handover between two real `plural-host` processes, the way the terminal client runs them."""

import asyncio
import json
import subprocess
import sys
from collections.abc import AsyncGenerator
from contextlib import suppress
from pathlib import Path
from typing import IO, Any

import pytest
from tests.e2e.support import CLIENT, RelayServer, Watcher

from plural.client.reconnect import JoinLink, SessionClient
from plural.protocol.commands import HostHandoverOffer, PromptSubmit
from plural.protocol.events import HostHandoverOffered, RunEnded, SessionWelcome
from plural.protocol.models import HOST_PARTICIPANT_ID, Role

ROOM = "r_process_handover"
HOST = str(Path(sys.executable).parent / "plural-host")


def start(tmp: Path, who: str, *args: str, relay: str) -> subprocess.Popen[str]:
    workspace = tmp / f"ws_{who}"
    workspace.mkdir(exist_ok=True)
    environment = {
        "PLURAL_DATA_DIR": str(tmp / f"data_{who}"),
        "PLURAL_PROVIDER": "fake",
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp),
    }
    return subprocess.Popen(
        [
            HOST,
            "host",
            "--json",
            "--relay",
            relay,
            "--mcp-url",
            "",
            "--workspace",
            str(workspace),
            "--name",
            who,
            *args,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        text=True,
    )


async def line(stream: IO[str] | None) -> dict[str, Any]:
    assert stream is not None
    async with asyncio.timeout(60):
        raw = await asyncio.to_thread(stream.readline)
    assert raw, "the host closed its output"
    return json.loads(raw)


@pytest.fixture
async def relay() -> AsyncGenerator[RelayServer]:
    server = RelayServer()
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


async def test_two_host_processes_hand_a_room_over(tmp_path: Path, relay: RelayServer) -> None:
    old = start(tmp_path, "Bob", "--room", ROOM, "--admission", "open", relay=relay.url)
    new: subprocess.Popen[str] | None = None
    watchers: list[Watcher] = []
    try:
        ready = await line(old.stdout)
        assert ready["type"] == "ready"
        assert "notes" not in ready  # an ordinary host says nothing about a takeover

        async def watch(link: str, name: str) -> Watcher:
            watcher = Watcher(SessionClient(JoinLink.parse(link), name=name, client=CLIENT))
            watchers.append(watcher)
            await watcher.next(SessionWelcome)
            return watcher

        owner = await watch(ready["host_link"], "Bob")
        alia = await watch(ready["guest_link"], "Alia")
        await alia.client.send(PromptSubmit(text="hello"))
        await owner.next(RunEnded)
        me = alia.client.projection.me
        assert me is not None
        assert me.role is Role.PARTICIPANT
        welcome = next(e for e in alia.events if isinstance(e, SessionWelcome))
        await owner.client.send(HostHandoverOffer(participant_id=me.id))
        await alia.next(HostHandoverOffered)

        own_link = f"{relay.url}/{ROOM}?token={welcome.token}"
        new = start(tmp_path, "Alia", "--takeover", own_link, relay=relay.url)
        taken = await line(new.stdout)
        assert taken["type"] == "ready"
        assert taken["room"] == ROOM
        # Her folder is not the old host's, and she is told so before the agent works in it.
        assert taken["host_link"].startswith(f"{relay.url}/{ROOM}?token=")

        # The old process says it is done with the room, and ends without failing.
        said = await line(old.stdout)
        assert said == {"type": "handed_over"}
        assert await asyncio.to_thread(old.wait, 30) == 0

        # The room is the same one, with Alia as its host and Bob in it as a participant.
        boss = await watch(taken["host_link"], "Alia")
        assert boss.client.projection.me is not None
        assert boss.client.projection.me.id == HOST_PARTICIPANT_ID
        assert boss.client.projection.state.participants[HOST_PARTICIPANT_ID].name == "Alia"
        assert boss.client.projection.state.handovers == 1
        assert any(e.text == "hello" for e in boss.client.projection.state.transcript)
    finally:
        for watcher in watchers:
            await watcher.stop()
        for child in (old, new):
            if child is not None and child.poll() is None:
                if child.stdin is not None:
                    with suppress(OSError):
                        child.stdin.close()
                child.terminate()
                with suppress(subprocess.TimeoutExpired):
                    child.wait(timeout=10)
