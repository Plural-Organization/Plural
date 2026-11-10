import asyncio
import json
import os
import secrets
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from typing import Any, Final, cast

import structlog
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException

from plural.host.chat_import import label
from plural.protocol.relay import USER_AGENT

log = structlog.get_logger(__name__)

SECRET_FILE: Final = "import_secret"
PATH: Final = "/i/"
MAX_OPEN: Final = 4

# What the gateway asks of us: (source, title, context) -> did the host accept
Offer = Callable[[str, str, str], Awaitable[bool]]


def load_or_create_secret(state_dir: Path) -> str:
    """The secret of this machine's import address. Made once, so the address never changes."""
    path = state_dir / SECRET_FILE
    if path.exists():
        found = path.read_text().strip()
        if found:
            return found
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    secret = secrets.token_urlsafe(32)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(secret)
    return secret


def _base(gateway: str) -> str:
    return gateway.rstrip("/")


def import_address(gateway: str, secret: str) -> str:
    """What a chat service is connected to: https://<gateway>/i/<secret>."""
    base = _base(gateway).replace("wss://", "https://", 1).replace("ws://", "http://", 1)
    return f"{base}{PATH}{secret}"


def _socket_url(gateway: str) -> str:
    base = _base(gateway).replace("https://", "wss://", 1).replace("http://", "ws://", 1)
    return f"{base}/host"


class McpLink:
    """Keeps this host connected to the MCP gateway, so a chat service can offer it a chat."""

    def __init__(
        self, gateway: str, secret: str, offer: Offer, *, max_delay_s: float = 30.0
    ) -> None:
        self._url = _socket_url(gateway)
        self._secret = secret
        self._offer = offer
        self._max_delay_s = max_delay_s

    async def serve(self) -> None:
        delay = 0.5
        while True:
            try:
                async with connect(self._url, user_agent_header=USER_AGENT) as socket:
                    await socket.send(json.dumps({"type": "hello", "secret": self._secret}))
                    delay = 0.5
                    await self._listen(socket)
            except (OSError, WebSocketException) as error:
                log.warning("mcp_link.disconnected", error=str(error))
            await asyncio.sleep(delay)
            delay = min(delay * 2, self._max_delay_s)

    async def _listen(self, socket: ClientConnection) -> None:
        tasks: set[asyncio.Task[None]] = set()
        try:
            async for raw in socket:
                message = _object(raw)
                if message.get("type") != "offer" or len(tasks) >= MAX_OPEN:
                    continue
                task = asyncio.create_task(self._answer(socket, message))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
        finally:
            for task in tasks:
                task.cancel()

    async def _answer(self, socket: ClientConnection, offer: dict[str, Any]) -> None:
        context = offer.get("context")
        accepted = False
        if isinstance(context, str) and context.strip():
            source = label(str(offer.get("source") or ""), "Chat")
            title = label(str(offer.get("title") or ""), "untitled")
            try:
                accepted = await self._offer(source, title, context.strip())
            except Exception:
                log.exception("mcp_link.offer_failed")
        with suppress(WebSocketException):
            await socket.send(
                json.dumps({"type": "answer", "id": offer.get("id"), "accepted": accepted})
            )


def _object(raw: str | bytes) -> dict[str, Any]:
    try:
        value: Any = json.loads(raw)
    except ValueError:
        return {}
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}
