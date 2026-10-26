from pathlib import Path

from plural.agent.sandbox.local import LocalBackend
from plural.agent.tools.streaming import MAX_BATCH_LINES, MAX_STREAMED_CHARS, LineStream


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_complete_lines_are_batched_and_partial_ones_wait() -> None:
    clock = Clock()
    sent: list[str] = []
    stream = LineStream(sent.append, clock=clock)

    stream.feed("one\ntw")
    assert sent == []
    clock.now = 0.2
    stream.feed("o\nthr")
    assert sent == ["one\ntwo\n"]
    clock.now = 0.5
    stream.feed("ee\n")
    assert sent == ["one\ntwo\n", "three\n"]
    stream.feed("tail")
    stream.flush()
    assert sent == ["one\ntwo\n", "three\n"]


def test_a_burst_of_lines_is_sent_in_one_event() -> None:
    sent: list[str] = []
    stream = LineStream(sent.append, clock=Clock())
    stream.feed("x\n" * MAX_BATCH_LINES)
    assert len(sent) == 1
    assert sent[0].count("\n") == MAX_BATCH_LINES


def test_streaming_stops_after_the_cap_but_flush_is_safe() -> None:
    sent: list[str] = []
    stream = LineStream(sent.append, clock=Clock())
    line = "y" * 99 + "\n"
    for _ in range(MAX_STREAMED_CHARS // 100 + 50):
        stream.feed(line)
    stream.flush()
    assert sum(len(chunk) for chunk in sent) == MAX_STREAMED_CHARS


async def test_the_local_backend_streams_chunks_and_returns_everything(tmp_path: Path) -> None:
    chunks: list[str] = []
    result = await LocalBackend().run(
        "printf 'héllo\\n'; sleep 0.1; printf 'wörld\\n'",
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin"},
        timeout=10,
        on_output=chunks.append,
    )
    assert result.exit_code == 0
    assert result.output == "héllo\nwörld\n"
    assert "".join(chunks) == result.output
    assert len(chunks) >= 2


async def test_a_multibyte_character_split_across_reads_is_kept_whole(tmp_path: Path) -> None:
    chunks: list[str] = []
    command = "printf '\\xe2\\x82'; sleep 0.1; printf '\\xac\\n'"
    result = await LocalBackend().run(
        command, cwd=tmp_path, env={"PATH": "/usr/bin:/bin"}, timeout=10, on_output=chunks.append
    )
    assert result.output == "€\n"
    assert "".join(chunks) == "€\n"


async def test_a_timeout_still_reports_a_timeout(tmp_path: Path) -> None:
    result = await LocalBackend().run(
        "printf 'start\\n'; sleep 5",
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin"},
        timeout=0.3,
    )
    assert result.timed_out
