"""How fast the harness itself is, without a model. See benchmarks/README.md."""

import argparse
import asyncio
import json
import logging
import statistics
import sys
import tempfile
import time
from collections.abc import Callable, Coroutine
from pathlib import Path
from urllib.parse import urlsplit

import structlog
from tests.e2e.support import CLIENT, Session, running_session
from tests.loop_support import StubGate, collect, make_loop, turn

from plural.agent.loop import LoopLimits
from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.client.reconnect import JoinLink, SessionClient
from plural.core.state import reduce
from plural.protocol.commands import ChatSend, PermissionModeSet, PromptSubmit
from plural.protocol.events import ChatPosted, Event, RunEnded, SessionWelcome
from plural.protocol.models import PermissionMode, Role, SessionState

BASELINE = Path(__file__).with_name("baseline.json")
# A case may take this many times its baseline before --check fails: CI machines are noisy.
TOLERANCE = 3
ROUNDS = 5


class Listener:
    """Hears a client's events at once, so a measure does not include a polling interval."""

    def __init__(self, client: SessionClient) -> None:
        self.client = client
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._task = asyncio.create_task(self._pump())

    async def _pump(self) -> None:
        async for event in self.client.events():
            self._queue.put_nowait(event)

    async def until[E: Event](self, kind: type[E]) -> E:
        async with asyncio.timeout(30):
            while True:
                event = await self._queue.get()
                if isinstance(event, kind):
                    return event

    async def stop(self) -> None:
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)


async def join(link: str, name: str) -> Listener:
    listener = Listener(SessionClient(JoinLink.parse(link), name=name, client=CLIENT))
    await listener.until(SessionWelcome)
    return listener


def tool_script(steps: int, path: str = "a.txt") -> FakeProvider:
    # The repeat guard counts equal calls in a row, so every call differs from the one before.
    turns = [use_tool("read", f"call_{i}", path=path, offset=i % 2) for i in range(steps)]
    return FakeProvider([*turns, reply("Done.")])


async def loop_step(tmp: Path) -> float:
    """One model turn and one tool call through the loop, in ms."""
    steps = 200
    loop = make_loop(tmp, tool_script(steps), StubGate(), LoopLimits(max_turns=steps + 1))
    started = time.perf_counter()
    await collect(loop, turn("go"))
    return (time.perf_counter() - started) * 1000 / steps


async def long_conversation(tmp: Path) -> float:
    """One prompt on top of a conversation of 1,000 tool calls, in ms."""
    steps = 1000
    provider = tool_script(steps)
    limits = LoopLimits(max_turns=steps + 2, context_window=100_000_000)
    loop = make_loop(tmp, provider, StubGate(), limits)
    await collect(loop, turn("go"))
    provider.enqueue(reply("Again."))
    started = time.perf_counter()
    await collect(loop, turn("again"))
    return (time.perf_counter() - started) * 1000


async def replay(tmp: Path) -> float:
    """Rebuilding the state from a session's log, in ms per 1,000 events."""
    provider = tool_script(50, "notes.txt")
    async with running_session(tmp, relayed=False, provider=provider) as session:
        owner = await join(session.host.host_link, "Host")
        await owner.client.send(PermissionModeSet(mode=PermissionMode.AUTO))
        await owner.client.send(PromptSubmit(text="go"))
        await owner.until(RunEnded)
        await owner.stop()
        records = await session.host.store.read()
    started = time.perf_counter()
    for _ in range(20):
        state = SessionState()
        for record in records:
            state = reduce(state, record)
    return (time.perf_counter() - started) * 1000 / (20 * len(records)) * 1000


async def host_start(tmp: Path) -> float:
    """From nothing to a host that takes connections, and then a welcomed owner, in ms."""
    started = time.perf_counter()
    async with running_session(tmp, relayed=False, provider=FakeProvider()) as session:
        # A client that knocks before the port is open waits out its reconnect backoff instead.
        port = urlsplit(session.host.host_link).port or 0
        while True:
            try:
                _, writer = await asyncio.open_connection("127.0.0.1", port)
            except OSError:
                await asyncio.sleep(0.001)
                continue
            writer.close()
            break
        owner = await join(session.host.host_link, "Host")
        taken = time.perf_counter() - started
        await owner.stop()
    return taken * 1000


async def prompt_round(session: Session) -> float:
    owner = await join(session.host.host_link, "Host")
    await owner.client.send(PermissionModeSet(mode=PermissionMode.AUTO))
    taken: list[float] = []
    for _ in range(20):
        started = time.perf_counter()
        await owner.client.send(PromptSubmit(text="hi"))
        await owner.until(RunEnded)
        taken.append(time.perf_counter() - started)
    await owner.stop()
    return statistics.median(taken) * 1000


async def prompt_direct(tmp: Path) -> float:
    """A prompt to the end of its run with an instant model, in ms."""
    async with running_session(tmp, relayed=False, provider=FakeProvider()) as session:
        return await prompt_round(session)


async def prompt_relayed(tmp: Path) -> float:
    """The same through a local relay, in ms."""
    async with running_session(tmp, relayed=True, provider=FakeProvider()) as session:
        return await prompt_round(session)


async def fanout(tmp: Path) -> float:
    """A chat message reaching ten guests, in ms."""
    async with running_session(tmp, relayed=False, provider=FakeProvider()) as session:
        host = session.host
        owner = await join(host.host_link, "Host")
        guests = [
            await join(host.invites.create(Role.PARTICIPANT, 600).link, f"Guest {index}")
            for index in range(10)
        ]
        taken: list[float] = []
        for index in range(20):
            started = time.perf_counter()
            await owner.client.send(ChatSend(text=f"message {index}"))
            await asyncio.gather(*(guest.until(ChatPosted) for guest in guests))
            taken.append(time.perf_counter() - started)
        for listener in (owner, *guests):
            await listener.stop()
    return statistics.median(taken) * 1000


def calibrate() -> float:
    """Plain Python work in ms, so numbers from two machines can be compared."""
    started = time.perf_counter()
    total = 0
    for index in range(3_000_000):
        total += index % 7
    return (time.perf_counter() - started) * 1000 + (total & 0)


CASES: dict[str, Callable[[Path], Coroutine[None, None, float]]] = {
    "loop_step": loop_step,
    "long_conversation": long_conversation,
    "replay_per_1k_events": replay,
    "host_start": host_start,
    "prompt_direct": prompt_direct,
    "prompt_relayed": prompt_relayed,
    "fanout_10_guests": fanout,
}


def measure(rounds: int, only: list[str] | None) -> dict[str, float]:
    """The best of a few rounds of each case: noise only ever makes a run slower."""
    numbers: dict[str, float] = {}
    for name, case in CASES.items():
        if only and name not in only:
            continue
        best = float("inf")
        for _ in range(rounds):
            with tempfile.TemporaryDirectory() as folder:
                best = min(best, asyncio.run(case(Path(folder).resolve())))
        numbers[name] = round(best, 3)
        print(f"{name:24} {best:10.3f} ms", flush=True)
    return numbers


def regressions(numbers: dict[str, float], machine: float) -> list[str]:
    baseline = json.loads(BASELINE.read_text())
    scale = machine / baseline["calibration_ms"]
    found: list[str] = []
    for name, value in numbers.items():
        if name not in baseline["cases"]:
            continue
        allowed = baseline["cases"][name] * scale * TOLERANCE
        if value > allowed:
            found.append(f"{name}: {value:.3f} ms, allowed {allowed:.3f} ms")
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=ROUNDS)
    parser.add_argument("--case", action="append", choices=sorted(CASES))
    parser.add_argument("--check", action="store_true", help="fail on a slowdown from the baseline")
    parser.add_argument("--save", action="store_true", help="write these numbers as the baseline")
    args = parser.parse_args()
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.ERROR))
    # A client torn down mid-reconnect leaves a closed future behind; that is not a measure.
    logging.getLogger("asyncio").setLevel(logging.CRITICAL)
    machine = min(calibrate() for _ in range(5))
    print(f"{'calibration':24} {machine:10.3f} ms", flush=True)
    numbers = measure(args.rounds, args.case)
    if args.save:
        saved = {"calibration_ms": round(machine, 3), "cases": numbers}
        BASELINE.write_text(json.dumps(saved, indent=2) + "\n")
    if args.check:
        found = regressions(numbers, machine)
        for line in found:
            print(f"slower than the baseline: {line}", file=sys.stderr)
        return 1 if found else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
