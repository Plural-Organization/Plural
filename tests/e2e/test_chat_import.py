import asyncio
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from plural.agent.providers.fake import FakeProvider
from plural.protocol.commands import ApprovalRespond
from plural.protocol.events import ApprovalRequested, BriefingImported
from plural.protocol.models import ApprovalDecision
from tests.e2e.support import Session, running_session

NOTE = "Goal: move the billing page to the new API. Done: the list view. Left: the invoice PDF."


def post(url: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any] | None]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json", "user-agent": "claude-connector/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            text = response.read().decode()
            return response.status, json.loads(text) if text else None
    except urllib.error.HTTPError as error:
        return error.code, None


async def rpc(url: str, method: str, **params: Any) -> tuple[int, dict[str, Any] | None]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    return await asyncio.to_thread(post, url, payload)


def link(session: Session) -> str:
    assert session.host.import_url is not None
    return session.host.import_url.replace("ws://", "http://")


async def test_a_chat_service_adds_its_context_once_the_host_accepts(tmp_path: Path) -> None:
    async with running_session(tmp_path, relayed=True, provider=FakeProvider([])) as session:
        owner = await session.owner()
        url = link(session)

        status, body = await rpc(url, "initialize", protocolVersion="2025-06-18")
        assert status == 200
        assert body is not None
        assert body["result"]["serverInfo"]["name"] == "plural"
        status, body = await rpc(url, "tools/list")
        assert body is not None
        assert [tool["name"] for tool in body["result"]["tools"]] == ["add_data_to_session"]

        call = asyncio.create_task(
            rpc(
                url,
                "tools/call",
                name="add_data_to_session",
                arguments={"context": NOTE, "title": "Billing page", "source": "Claude"},
            )
        )
        asked = await owner.next(ApprovalRequested)
        assert asked.approval.call.name == "import_chat"
        assert asked.approval.call.args["characters"] == len(NOTE)
        await owner.client.send(
            ApprovalRespond(approval_id=asked.approval.id, decision=ApprovalDecision.ONCE)
        )
        status, body = await call
        assert status == 200
        assert body is not None
        assert body["result"]["isError"] is False

        imported = await owner.next(BriefingImported)
        assert imported.item.source == "Claude chat Billing page"
        assert imported.text == NOTE


async def test_a_declined_offer_adds_nothing_and_says_so(tmp_path: Path) -> None:
    async with running_session(tmp_path, relayed=True, provider=FakeProvider([])) as session:
        owner = await session.owner()
        call = asyncio.create_task(
            rpc(
                link(session),
                "tools/call",
                name="add_data_to_session",
                arguments={"context": NOTE},
            )
        )
        asked = await owner.next(ApprovalRequested)
        await owner.client.send(
            ApprovalRespond(approval_id=asked.approval.id, decision=ApprovalDecision.REJECT)
        )
        status, body = await call
        assert status == 200
        assert body is not None
        assert body["result"]["isError"] is True
        assert not [e for e in owner.events if isinstance(e, BriefingImported)]


async def test_a_wrong_token_and_a_missing_room_get_nothing(tmp_path: Path) -> None:
    async with running_session(tmp_path, relayed=True, provider=FakeProvider([])) as session:
        url = link(session)
        status, _ = await rpc(url[:-3] + "xxx", "tools/list")
        assert status == 404
        status, _ = await rpc(url.replace("r_e2e", "r_nobody"), "tools/list")
        assert status == 404
        assert session.host.import_url is not None


async def test_the_link_is_the_same_after_a_restart(tmp_path: Path) -> None:
    async with running_session(tmp_path, relayed=True, provider=FakeProvider([])) as first:
        before = first.host.import_url
    async with running_session(tmp_path, relayed=True, provider=FakeProvider([])) as second:
        after = second.host.import_url
    assert before is not None
    assert before.rsplit("/", 1)[1] == (after or "").rsplit("/", 1)[1]


async def test_a_host_without_a_relay_has_no_import_link(tmp_path: Path) -> None:
    async with running_session(tmp_path, relayed=False, provider=FakeProvider([])) as session:
        assert session.host.import_url is None
