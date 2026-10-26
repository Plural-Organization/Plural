from pathlib import Path

from tests.loop_support import StubGate, collect, make_loop, turn

from plural.agent.messages import AssistantTurn
from plural.agent.providers.base import NativeContent, NativeReady
from plural.agent.providers.fake import FakeProvider, reply, use_tool


async def test_a_swapped_provider_answers_next_and_old_native_blocks_are_not_replayed(
    tmp_path: Path,
) -> None:
    native = NativeContent(provider="anthropic", blocks=({"type": "thinking", "signature": "s"},))
    old = FakeProvider(
        [(*use_tool("read", path="a.txt"), NativeReady(content=native)), reply("old")]
    )
    new = FakeProvider([reply("from the new provider")])
    loop = make_loop(tmp_path, old, StubGate())
    await collect(loop, turn("first"))
    assert any(isinstance(m, AssistantTurn) and m.native == native for m in loop.conversation)

    loop.swap_provider(new, context_window=4096)
    assert not any(isinstance(m, AssistantTurn) and m.native for m in loop.conversation)

    await collect(loop, turn("second"))
    assert len(new.requests) == 1
    assert len(old.requests) == 2
    assert all(m.native is None for m in new.requests[0].messages)
    users = [m.content for m in new.requests[0].messages if m.role == "user"]
    assert [text.split("\n")[-1] for text in users] == ["first", "second"]


async def test_swapping_keeps_the_conversation_and_resets_what_depends_on_the_old_model(
    tmp_path: Path,
) -> None:
    loop = make_loop(tmp_path, FakeProvider([reply("a")]), StubGate())
    await collect(loop, turn("hello"))
    before = len(loop.conversation)
    loop.swap_provider(FakeProvider([reply("b")]), context_window=None)
    assert len(loop.conversation) == before
