from pathlib import Path

from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.protocol.commands import PromptSubmit
from plural.protocol.events import RunEnded, ToolsLoaded
from tests.e2e.support import running_session

BOARD = ["board_view", "board_draw", "board_move", "board_erase"]


async def test_loaded_tools_reach_the_room_and_survive_a_restart(tmp_path: Path) -> None:
    provider = FakeProvider(
        [use_tool("tool_search", query="draw shapes on the shared board"), reply("drawn")]
    )
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        await owner.client.send(PromptSubmit(text="sketch the plan"))
        loaded = await owner.next(ToolsLoaded)
        await owner.next(RunEnded)
        assert set(BOARD) <= set(loaded.tools)
        assert set(BOARD) <= set(owner.client.projection.state.loaded_tools)
        declared = [[schema.name for schema in request.tools] for request in provider.requests]
        assert "board_draw" not in declared[0]
        assert "tool_search" in declared[0]
        assert "board_draw" in declared[1]

    again = FakeProvider([reply("still here")])
    async with running_session(tmp_path, relayed=False, provider=again) as session:
        owner = await session.owner()
        await owner.client.send(PromptSubmit(text="and now?"))
        await owner.next(RunEnded)
        assert "board_draw" in [schema.name for schema in again.requests[0].tools]
