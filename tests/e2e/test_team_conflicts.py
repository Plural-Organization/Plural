import asyncio
import json
import subprocess
from collections.abc import AsyncGenerator
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.cli.main import app
from plural.client.reconnect import JoinLink, SessionClient
from plural.host import team_presence
from plural.host.bootstrap import build_host
from plural.host.config import HostSettings
from plural.host.team_presence import TeamPresence
from plural.protocol.commands import ApprovalRespond, PromptSubmit
from plural.protocol.events import ApprovalRequested, RunEnded, SessionSnapshot
from plural.protocol.models import ApprovalDecision
from plural.protocol.team import (
    CardDraft,
    Endpoint,
    EndpointKind,
    PresenceCard,
    PresencePeers,
    SessionStatus,
    Touch,
)
from tests.e2e.support import CLIENT, RelayServer, Watcher, free_port
from tests.e2e.team_support import connect_as, two_members

REMOTE = "git@github.com:Org/API.git"


@pytest.fixture
async def relay(tmp_path: Path) -> AsyncGenerator[RelayServer]:
    server = RelayServer(teams=tmp_path / "relay" / "teams.db")
    await server.start()
    yield server
    await server.stop()


def card(
    room: str, *files: str, repo_id: str | None = "github.com/org/api", branch: str = "main"
) -> CardDraft:
    return CardDraft(
        room=room,
        repo="api",
        branch=branch,
        status=SessionStatus.RUNNING,
        endpoints=(Endpoint(kind=EndpointKind.RELAY, url=f"wss://relay.example/{room}"),),
        repo_id=repo_id,
        touching=tuple(
            Touch(path=path, at=datetime.now(UTC) - timedelta(minutes=2)) for path in files
        ),
    )


async def answer(socket: object) -> PresencePeers:
    async with asyncio.timeout(5):
        return PresencePeers.model_validate_json(await socket.recv())  # type: ignore[attr-defined]


async def test_the_directory_tells_each_host_what_the_others_in_its_repository_changed(
    relay: RelayServer, tmp_path: Path
) -> None:
    vlad, alia = await two_members(relay, tmp_path)
    async with connect_as(vlad, relay) as first, connect_as(alia, relay) as second:
        await first.send(PresenceCard(card=card("r_vlad", "src/auth.py")).model_dump_json())
        assert (await answer(first)).peers == ()

        await second.send(
            PresenceCard(card=card("r_alia", "src/db.py", branch="feat/x")).model_dump_json()
        )
        (peer,) = (await answer(second)).peers
        assert (peer.owner, peer.branch, peer.same_branch) == ("vlad", "main", False)
        assert [touch.path for touch in peer.touched] == ["src/auth.py"]

        await first.send(PresenceCard(card=card("r_vlad", "src/auth.py")).model_dump_json())
        (seen,) = (await answer(first)).peers
        assert [touch.path for touch in seen.touched] == ["src/db.py"]


async def test_two_cards_on_the_same_file_are_listed_as_a_conflict_and_other_repositories_are_not(
    relay: RelayServer, tmp_path: Path
) -> None:
    vlad, alia = await two_members(relay, tmp_path)
    async with connect_as(vlad, relay) as first, connect_as(alia, relay) as second:
        await first.send(
            PresenceCard(card=card("r_vlad", "src/auth.py", "src/a.py")).model_dump_json()
        )
        await answer(first)
        await second.send(
            PresenceCard(card=card("r_alia", "src/auth.py", "src/b.py")).model_dump_json()
        )
        await answer(second)
        client = await vlad.client()
        cards = {entry.owner: entry for entry in (await client.sessions()).sessions}
        (conflict,) = cards["vlad"].conflicts
        assert (conflict.owner, conflict.paths, conflict.same_branch) == (
            "alia",
            ("src/auth.py",),
            True,
        )
        assert cards["alia"].conflicts[0].owner == "vlad"

        await second.send(
            PresenceCard(
                card=card("r_alia", "src/auth.py", repo_id="github.com/org/web")
            ).model_dump_json()
        )
        await answer(second)
        cards = {entry.owner: entry for entry in (await client.sessions()).sessions}
        assert cards["vlad"].conflicts == ()
        assert cards["alia"].conflicts == ()


async def test_plural_ls_shows_the_conflict(
    relay: RelayServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vlad, alia = await two_members(relay, tmp_path)
    async with connect_as(vlad, relay) as first, connect_as(alia, relay) as second:
        await first.send(PresenceCard(card=card("r_vlad", "src/auth.py")).model_dump_json())
        await answer(first)
        await second.send(PresenceCard(card=card("r_alia", "src/auth.py")).model_dump_json())
        await answer(second)
        monkeypatch.setenv("PLURAL_DATA_DIR", str(vlad.root / "data"))
        runner = CliRunner()
        shown = await asyncio.to_thread(runner.invoke, app, ["ls"])
        assert "⚠ alia also changed src/auth.py" in shown.output
        raw = await asyncio.to_thread(runner.invoke, app, ["ls", "--json"])
        rows = {row["owner"]: row for row in json.loads(raw.output)}
        assert rows["vlad"]["conflicts"][0]["owner"] == "alia"


async def test_a_host_is_warned_before_it_edits_a_file_a_teammate_just_changed(
    relay: RelayServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(team_presence, "POLL_S", 0.05)
    monkeypatch.setattr(team_presence, "HEARTBEAT_S", 0.2)
    vlad, alia = await two_members(relay, tmp_path)
    workspace = tmp_path / "ws"
    (workspace / "src").mkdir(parents=True)
    for args in (["init", "-q"], ["remote", "add", "origin", REMOTE]):
        await asyncio.to_thread(subprocess.run, ["git", "-C", str(workspace), *args], check=True)
    settings = HostSettings(
        workspace=workspace,
        data_dir=vlad.root / "data",
        room="r_live",
        port=free_port(),
        relay_url=relay.url,
        provider="fake",
        team=True,
    )
    provider = FakeProvider(
        [
            use_tool("write", "c1", path="src/auth.py", content="print(1)\n"),
            reply("done"),
            use_tool("write", "c2", path="src/free.py", content="print(2)\n"),
            reply("done again"),
        ]
    )
    host = await build_host(settings, provider=provider)
    serving = asyncio.create_task(host.serve())
    presence = asyncio.create_task(TeamPresence(host, settings, vlad.store).run())
    owner = Watcher(SessionClient(JoinLink.parse(host.host_link), name="vlad", client=CLIENT))
    try:
        async with connect_as(alia, relay) as socket:
            await socket.send(PresenceCard(card=card("r_alia", "src/auth.py")).model_dump_json())
            await answer(socket)
            assert host.conflicts is not None
            async with asyncio.timeout(5):
                while not host.conflicts.peers:
                    await asyncio.sleep(0.05)

            await owner.next(SessionSnapshot)
            await owner.client.send(PromptSubmit(text="edit auth"))
            asked = (await owner.next(ApprovalRequested)).approval
            assert len(asked.warnings) == 1
            assert asked.warnings[0].startswith("src/auth.py was also changed by alia")
            assert asked.warnings[0].endswith(" min ago on main")
            await owner.client.send(
                ApprovalRespond(approval_id=asked.id, decision=ApprovalDecision.ONCE)
            )
            await owner.next(RunEnded)

            await owner.client.send(PromptSubmit(text="edit something else"))
            free = (await owner.next(ApprovalRequested)).approval
            assert free.warnings == ()
            await owner.client.send(
                ApprovalRespond(approval_id=free.id, decision=ApprovalDecision.ONCE)
            )
            await owner.next(RunEnded)

            async with asyncio.timeout(5):
                while True:
                    cards = {c.owner: c for c in (await (await alia.client()).sessions()).sessions}
                    if {touch.path for touch in cards["vlad"].touching} == {
                        "src/auth.py",
                        "src/free.py",
                    }:
                        break
                    await asyncio.sleep(0.1)
            assert cards["vlad"].repo_id == "github.com/org/api"
            assert cards["vlad"].conflicts[0].owner == "alia"
            assert cards["vlad"].conflicts[0].paths == ("src/auth.py",)
    finally:
        await owner.stop()
        presence.cancel()
        serving.cancel()
        for task in (presence, serving):
            with suppress(asyncio.CancelledError):
                await task
        await host.close()
