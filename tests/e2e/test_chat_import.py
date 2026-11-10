import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from websockets.asyncio.server import ServerConnection, serve

from plural.protocol.commands import ApprovalRespond
from plural.protocol.events import ApprovalRequested, BriefingImported
from plural.protocol.models import ApprovalDecision
from tests.doubles import FakeProvider
from tests.e2e.support import Session, running_session

NOTE = "Goal: move the billing page to the new API. Done: the list view. Left: the invoice PDF."


class Gateway:
    """A stand-in for the MCP gateway the host connects out to."""

    def __init__(self) -> None:
        self.socket: ServerConnection | None = None
        self.connected = asyncio.Event()
        self.hellos: list[str] = []

    async def handler(self, socket: ServerConnection) -> None:
        self.hellos.append(json.loads(await socket.recv())["secret"])
        self.socket = socket
        self.connected.set()
        await socket.wait_closed()

    async def offer(self, **fields: Any) -> dict[str, Any]:
        assert self.socket is not None
        await self.socket.send(json.dumps({"type": "offer", "id": "o1", **fields}))
        return json.loads(await asyncio.wait_for(self.socket.recv(), 20))


@asynccontextmanager
async def connected(tmp_path: Path) -> AsyncGenerator[tuple[Session, Gateway]]:
    gateway = Gateway()
    async with serve(gateway.handler, "127.0.0.1", 0) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        async with running_session(
            tmp_path,
            relayed=False,
            provider=FakeProvider([]),
            overrides={"mcp_url": f"http://127.0.0.1:{port}"},
        ) as session:
            await asyncio.wait_for(gateway.connected.wait(), 10)
            yield session, gateway


async def test_a_chat_service_adds_its_context_once_the_host_accepts(tmp_path: Path) -> None:
    async with connected(tmp_path) as (session, gateway):
        owner = await session.owner()
        assert session.host.import_url is not None
        assert session.host.import_url.endswith(f"/i/{gateway.hellos[0]}")

        offered = asyncio.create_task(
            gateway.offer(source="Claude", title="Billing page", context=NOTE)
        )
        asked = await owner.next(ApprovalRequested)
        assert asked.approval.call.name == "import_chat"
        assert asked.approval.call.args["characters"] == len(NOTE)
        await owner.client.send(
            ApprovalRespond(approval_id=asked.approval.id, decision=ApprovalDecision.ONCE)
        )
        assert (await offered)["accepted"] is True

        imported = await owner.next(BriefingImported)
        assert imported.item.source == "Claude chat Billing page"
        assert imported.text == NOTE


async def test_a_declined_offer_adds_nothing_and_says_so(tmp_path: Path) -> None:
    async with connected(tmp_path) as (session, gateway):
        owner = await session.owner()
        offered = asyncio.create_task(gateway.offer(source="Claude", title="x", context=NOTE))
        asked = await owner.next(ApprovalRequested)
        await owner.client.send(
            ApprovalRespond(approval_id=asked.approval.id, decision=ApprovalDecision.REJECT)
        )
        assert (await offered)["accepted"] is False
        assert not [e for e in owner.events if isinstance(e, BriefingImported)]


async def test_the_address_is_the_same_for_the_next_session(tmp_path: Path) -> None:
    async with connected(tmp_path) as (first, _):
        before = first.host.import_url
    async with connected(tmp_path) as (second, _):
        after = second.host.import_url
    assert before is not None
    assert before.rsplit("/", 1)[1] == (after or "").rsplit("/", 1)[1]


async def test_a_host_without_a_gateway_has_no_import_address(tmp_path: Path) -> None:
    async with running_session(tmp_path, relayed=False, provider=FakeProvider([])) as session:
        assert session.host.import_url is None
