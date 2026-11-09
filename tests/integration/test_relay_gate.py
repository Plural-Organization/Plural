import asyncio
import urllib.error
import urllib.request
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
import uvicorn
from tests.e2e.support import free_port
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from plural.protocol.relay import USER_AGENT
from plural.relay.app import create_app

WEB = "https://web.example.com"


@asynccontextmanager
async def gated_relay() -> AsyncGenerator[str]:
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(clients_only=True, web_origins=[WEB + "/"]),
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    )
    task = asyncio.create_task(server.serve())
    async with asyncio.timeout(10):
        while not server.started:
            await asyncio.sleep(0.01)
    try:
        yield f"127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task


def status(url: str, **headers: str) -> int:
    request = urllib.request.Request(url, headers={"user-agent": "", **headers})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


async def get(url: str, **headers: str) -> int:
    return await asyncio.to_thread(status, url, **headers)


async def test_only_plural_clients_and_the_web_client_get_through() -> None:
    async with gated_relay() as relay:
        metrics = f"http://{relay}/metrics"
        assert await get(metrics) == 403
        assert await get(metrics, **{"user-agent": "Python-urllib/3.12"}) == 403
        assert await get(metrics, **{"user-agent": "curl/8.7"}) == 403
        assert await get(metrics, **{"user-agent": USER_AGENT}) == 200
        assert await get(metrics, **{"user-agent": "Plural-Client"}) == 200
        assert await get(metrics, origin=WEB) == 200
        assert await get(metrics, origin="https://evil.example.com") == 403


async def test_the_health_check_stays_open() -> None:
    async with gated_relay() as relay:
        assert await get(f"http://{relay}/healthz") == 200


async def test_a_websocket_needs_the_plural_agent_too() -> None:
    async with gated_relay() as relay:
        with pytest.raises(InvalidStatus) as refused:
            async with connect(f"ws://{relay}/host/r_1"):
                pass
        assert refused.value.response.status_code == 403
        async with connect(f"ws://{relay}/host/r_1", user_agent_header=USER_AGENT) as socket:
            assert socket.protocol.state.name == "OPEN"
        async with connect(
            f"ws://{relay}/host/r_2", additional_headers={"origin": WEB}, user_agent_header=None
        ) as socket:
            assert socket.protocol.state.name == "OPEN"


async def test_the_import_link_is_open_to_chat_services_but_the_rest_stays_gated() -> None:
    def post(url: str) -> int:
        request = urllib.request.Request(
            url, data=b"{}", headers={"user-agent": "Anthropic-connector/1.0"}
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code

    async with gated_relay() as relay:
        # Past the gate, and then no host in the room to answer.
        assert await asyncio.to_thread(post, f"http://{relay}/mcp/r_x/token") == 404
        assert (
            await get(f"http://{relay}/metrics", **{"user-agent": "Anthropic-connector/1.0"}) == 403
        )
