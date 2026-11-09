import json
from typing import Any

from plural.host.chat_import import TOOL, ChatImport
from plural.protocol.commands import MAX_BRIEFING_CHARS
from plural.protocol.relay import CallReply, CallRequest

TOKEN = "secret-token"


class Desk:
    def __init__(self, accept: bool = True) -> None:
        self.accept = accept
        self.offers: list[tuple[str, str, str]] = []

    async def offer(self, source: str, title: str, text: str) -> bool:
        self.offers.append((source, title, text))
        return self.accept


async def ask(
    server: ChatImport, body: Any, token: str = TOKEN
) -> tuple[int, dict[str, Any] | list[Any] | None]:
    raw = await server.handle(CallRequest(token=token, body=json.dumps(body)).model_dump_json())
    reply = CallReply.model_validate_json(raw)
    return reply.status, json.loads(reply.body) if reply.body else None


def call(**arguments: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": TOOL, "arguments": arguments},
    }


async def test_it_introduces_itself_in_the_version_the_client_asks_for() -> None:
    server = ChatImport(Desk().offer, token=TOKEN)

    def asked(version: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": version},
        }

    status, body = await ask(server, asked("2025-03-26"))
    assert status == 200
    assert isinstance(body, dict)
    assert body["result"]["protocolVersion"] == "2025-03-26"
    assert body["result"]["capabilities"] == {"tools": {}}
    _, newer = await ask(server, asked("1999-01-01"))
    assert isinstance(newer, dict)
    assert newer["result"]["protocolVersion"] == "2025-06-18"


async def test_it_lists_one_tool_and_answers_a_ping() -> None:
    server = ChatImport(Desk().offer, token=TOKEN)
    _, listed = await ask(server, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert isinstance(listed, dict)
    [tool] = listed["result"]["tools"]
    assert tool["name"] == TOOL
    assert tool["inputSchema"]["required"] == ["context"]
    _, pong = await ask(server, {"jsonrpc": "2.0", "id": 3, "method": "ping"})
    assert pong == {"jsonrpc": "2.0", "id": 3, "result": {}}


async def test_a_notification_gets_no_body_and_an_unknown_method_an_error() -> None:
    server = ChatImport(Desk().offer, token=TOKEN)
    status, body = await ask(server, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert (status, body) == (202, None)
    _, unknown = await ask(server, {"jsonrpc": "2.0", "id": 4, "method": "resources/list"})
    assert isinstance(unknown, dict)
    assert unknown["error"]["code"] == -32601


async def test_a_batch_is_answered_in_a_batch() -> None:
    server = ChatImport(Desk().offer, token=TOKEN)
    status, body = await ask(
        server,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "ping"},
        ],
    )
    assert status == 200
    assert isinstance(body, list)
    assert [answer["id"] for answer in body] == [1, 2]


async def test_the_wrong_token_is_a_404_and_the_desk_is_never_asked() -> None:
    desk = Desk()
    server = ChatImport(desk.offer, token=TOKEN)
    status, _ = await ask(server, call(context="hello"), token="guess")
    assert status == 404
    assert desk.offers == []


async def test_the_host_decides_and_the_answer_says_which_way() -> None:
    desk = Desk()
    server = ChatImport(desk.offer, token=TOKEN)
    _, taken = await ask(server, call(context=" the note ", title="Billing", source="Claude"))
    assert isinstance(taken, dict)
    assert taken["result"]["isError"] is False
    assert desk.offers == [("Claude", "Billing", "the note")]
    desk.accept = False
    _, refused = await ask(server, call(context="the note"))
    assert isinstance(refused, dict)
    assert refused["result"]["isError"] is True
    assert desk.offers[-1][:2] == ("Chat", "untitled")


async def test_a_bad_call_is_an_error_result_the_model_can_act_on() -> None:
    desk = Desk()
    server = ChatImport(desk.offer, token=TOKEN)
    for arguments in ({}, {"context": "  "}, {"context": 5}):
        _, body = await ask(server, call(**arguments))
        assert isinstance(body, dict)
        assert body["result"]["isError"] is True
    _, big = await ask(server, call(context="x" * (MAX_BRIEFING_CHARS + 1)))
    assert isinstance(big, dict)
    assert "shorter" in big["result"]["content"][0]["text"]
    wrong = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "other"}}
    _, other = await ask(server, wrong)
    assert isinstance(other, dict)
    assert other["result"]["isError"] is True
    assert desk.offers == []


async def test_a_title_cannot_smuggle_markup_into_the_source_label() -> None:
    desk = Desk()
    server = ChatImport(desk.offer, token=TOKEN)
    await ask(server, call(context="note", title="<b>Hi</b>\nignore previous", source="!!!"))
    source, title, _ = desk.offers[0]
    assert source == "Chat"
    assert "<" not in title
    assert "\n" not in title
