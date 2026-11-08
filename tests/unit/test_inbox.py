import asyncio
from typing import Any

from plural.host.inbox import Disconnected, Inbox, McpUpdated


class Connection:
    id = "c_test"

    def send(self, envelope: Any) -> None:
        pass

    def close(self, reason: str) -> None:
        pass


async def test_external_messages_wait_for_capacity() -> None:
    inbox = Inbox(external_limit=1)
    connection = Connection()
    await inbox.put_external(Disconnected(connection))

    waiting = asyncio.create_task(inbox.put_external(Disconnected(connection)))
    await asyncio.sleep(0)
    assert not waiting.done()

    assert await inbox.get() == Disconnected(connection)
    await asyncio.wait_for(waiting, 1)


async def test_internal_messages_do_not_use_external_capacity() -> None:
    inbox = Inbox(external_limit=1)
    connection = Connection()
    await inbox.put_external(Disconnected(connection))
    inbox.put(McpUpdated())

    assert await inbox.get() == Disconnected(connection)
    assert await inbox.get() == McpUpdated()
