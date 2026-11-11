"""How well the harness solves real tasks on a real model. See benchmarks/README.md."""

import argparse
import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import structlog
from tests.e2e.support import free_port

from plural.client.connection import CommandRejected
from plural.client.reconnect import JoinLink, SessionClient
from plural.host.bootstrap import build_host
from plural.host.config import HostSettings
from plural.protocol.commands import ClientInfo, PermissionModeSet, PromptSubmit, RunAbort
from plural.protocol.events import (
    ContextCompacted,
    ContextUsage,
    Event,
    MessageEnded,
    MessageStarted,
    RunEnded,
    SessionWelcome,
    ToolEnded,
    ToolStarted,
    UsageRecorded,
)
from plural.protocol.models import PermissionMode, RunEndReason, Usage

HERE = Path(__file__).parent
TASKS = HERE / "tasks"
RESULTS = HERE.parent / "results"
CLIENT = ClientInfo(kind="eval", version="0")
CHECK_TIMEOUT_S = 120
# How long an aborted run has to end and say what it spent.
ABORT_WAIT_S = 15
# What `codex exec` runs with, as the Codex app server Plural talks to reads it from config.toml.
CODEX_EFFORT = "medium"
CODEX_TOOLS = {"command_execution", "file_change", "mcp_tool_call", "web_search"}
# Where a run's traces and raw logs are kept, set once the run starts.
kept: Path | None = None
# An OpenAI-compatible endpoint the run uses instead of the preset's own, for a local server.
base_url: str | None = None
MAX_LINE_BYTES = 16 * 1024 * 1024


@dataclass(slots=True)
class Task:
    id: str
    prompt: str
    timeout_s: int
    folder: Path


@dataclass(slots=True)
class Outcome:
    task: str
    # passed, failed, timeout, or error: the run itself broke, so it says nothing about the agent.
    status: str = "error"
    detail: str = ""
    seconds: float = 0
    model_turns: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    compactions: int = 0
    files_changed: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    # The fullest the context got, the model's window, and what filled it at that moment.
    context_peak: int = 0
    context_window: int = 0
    context_parts: dict[str, int] = field(default_factory=dict[str, int])
    tools: dict[str, int] = field(default_factory=dict[str, int])


def load_tasks(only: list[str] | None) -> list[Task]:
    tasks: list[Task] = []
    for folder in sorted(path for path in TASKS.iterdir() if path.is_dir()):
        if only and folder.name not in only:
            continue
        meta = tomllib.loads((folder / "task.toml").read_text())
        tasks.append(Task(folder.name, meta["prompt"], meta.get("timeout_s", 600), folder))
    return tasks


def git(workspace: Path, *args: str) -> str:
    identity = ("-c", "user.name=eval", "-c", "user.email=eval@plural.invalid")
    done = subprocess.run(
        ["git", *identity, *args], cwd=workspace, check=True, capture_output=True, text=True
    )
    return done.stdout


def prepare(task: Task, workspace: Path) -> None:
    """The task's repository as one commit, without the check: the agent never sees it."""
    shutil.copytree(task.folder / "repo", workspace, dirs_exist_ok=True)
    setup = task.folder / "setup.py"
    if setup.exists():
        subprocess.run([sys.executable, "-I", str(setup)], cwd=workspace, check=True)
    git(workspace, "init", "-q")
    # Running the code to confirm a fix leaves caches behind; they are not a change.
    (workspace / ".git" / "info" / "exclude").write_text("__pycache__/\nnode_modules/\n")
    git(workspace, "add", "-A")
    git(workspace, "commit", "-qm", "start")


def check(task: Task, workspace: Path, reply: Path) -> tuple[bool, str]:
    try:
        done = subprocess.run(
            [sys.executable, "-I", str(task.folder / "check.py"), str(reply)],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=CHECK_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return False, "the check timed out"
    return done.returncode == 0, (done.stdout + done.stderr).strip()[-500:]


def tally(outcome: Outcome, event: Event) -> None:
    match event:
        case MessageStarted():
            outcome.model_turns += 1
        case ToolStarted(call=call):
            outcome.tool_calls += 1
            outcome.tools[call.name] = outcome.tools.get(call.name, 0) + 1
        case ToolEnded(ok=False):
            outcome.tool_errors += 1
        case ContextCompacted():
            outcome.compactions += 1
        case ContextUsage(context=context) if context.tokens >= outcome.context_peak:
            outcome.context_peak = context.tokens
            outcome.context_window = context.window
            outcome.context_parts = {}
            for part in context.parts:
                name = f"{part.kind}:{part.name}" if part.name else str(part.kind)
                outcome.context_parts[name] = outcome.context_parts.get(name, 0) + part.tokens
        case _:
            pass


def ended(outcome: Outcome, event: RunEnded) -> None:
    match event.reason:
        case RunEndReason.STOP:
            outcome.status = "ran"
        case RunEndReason.ABORTED:
            pass
        case _:
            # A limit, a failed compaction or a refusal is the harness's to answer for.
            outcome.status = "failed"
            outcome.detail = event.error or f"the run ended: {event.reason.value}"


async def drive(task: Task, settings: HostSettings, outcome: Outcome) -> str:
    """Runs the prompt to its end and gives the agent's last message."""
    host = await build_host(settings)
    serving = asyncio.create_task(host.serve())
    client = SessionClient(JoinLink.parse(host.host_link), name="Eval", client=CLIENT)
    last = ""
    # Sub-agents and helpers spend outside the run's own count; the lines before its end add all.
    spent = Usage()
    try:
        events = client.events()
        async with asyncio.timeout(60):
            async for event in events:
                if isinstance(event, SessionWelcome):
                    break
        await client.send(PermissionModeSet(mode=PermissionMode.AUTO))
        await client.send(PromptSubmit(text=task.prompt))
        started = time.monotonic()
        limit = task.timeout_s
        async for event in until(events, started + limit, client):
            if event is None:
                outcome.status = "timeout"
                continue
            tally(outcome, event)
            match event:
                case MessageEnded(text=text) if text:
                    last = text
                case UsageRecorded(lines=lines):
                    for usage_line in lines:
                        spent = spent + usage_line.usage
                case RunEnded():
                    if outcome.status != "timeout":
                        ended(outcome, event)
                    break
                case _:
                    pass
        outcome.seconds = round(min(time.monotonic() - started, limit), 1)
    except (CommandRejected, ConnectionError, TimeoutError) as error:
        outcome.detail = f"{type(error).__name__}: {error}"
    finally:
        serving.cancel()
        await asyncio.gather(serving, return_exceptions=True)
        await host.close()
    outcome.input_tokens = spent.input_tokens
    outcome.output_tokens = spent.output_tokens
    outcome.cache_read_tokens = spent.cache_read_tokens
    outcome.cache_write_tokens = spent.cache_write_tokens
    return last


async def until(
    events: AsyncIterator[Event], deadline: float, client: SessionClient
) -> AsyncIterator[Event | None]:
    """The run's events, and None when time runs out: the run is then aborted and its end still
    awaited, so what it spent is counted."""
    aborted = False
    while True:
        wait = deadline - time.monotonic() if not aborted else ABORT_WAIT_S
        try:
            async with asyncio.timeout(max(wait, 0)):
                event = await anext(events)
        except TimeoutError:
            if aborted:
                return
            aborted = True
            yield None
            await client.send(RunAbort())
            continue
        except StopAsyncIteration:
            return
        yield event


def begin(task: Task, folder: str, preset: str, model: str) -> HostSettings:
    root = Path(folder).resolve()
    workspace = root / "ws"
    workspace.mkdir()
    prepare(task, workspace)
    return HostSettings(
        workspace=workspace,
        data_dir=root / "data",
        port=free_port(),
        preset=preset,
        model=model,
        base_url=base_url,
        browser="off",
        web_search=False,
    )


def judge(task: Task, workspace: Path, outcome: Outcome, reply: str) -> None:
    outcome.files_changed = len(git(workspace, "status", "--porcelain").splitlines())
    if outcome.status == "ran":
        answer = workspace.parent / "reply.txt"
        answer.write_text(reply)
        passed, outcome.detail = check(task, workspace, answer)
        outcome.status = "passed" if passed else "failed"


def tally_codex(outcome: Outcome, event: dict[str, Any]) -> None:
    """Codex's own events: it says what it ran and what it spent, not how full its context got."""
    item: dict[str, Any] = event.get("item") or {}
    if event.get("type") == "item.completed" and item.get("type") in CODEX_TOOLS:
        outcome.tool_calls += 1
        name = item["type"]
        outcome.tools[name] = outcome.tools.get(name, 0) + 1
        if item.get("status") == "failed" or item.get("exit_code") not in (None, 0):
            outcome.tool_errors += 1
    if event.get("type") == "turn.completed":
        usage: dict[str, int] = event.get("usage") or {}
        cached = usage.get("cached_input_tokens", 0)
        # Codex counts the cached part inside its input tokens; Plural counts the two apart.
        outcome.input_tokens += usage.get("input_tokens", 0) - cached
        outcome.cache_read_tokens += cached
        outcome.cache_write_tokens += usage.get("cache_write_input_tokens", 0)
        outcome.output_tokens += usage.get("output_tokens", 0)
        # One Codex turn holds many model requests it does not report, so model_turns stays 0.
        outcome.status = "ran"
    if event.get("type") in {"turn.failed", "error"}:
        outcome.detail = json.dumps(event)[:300]


async def drive_codex(task: Task, workspace: Path, model: str, outcome: Outcome) -> str:
    """The same task through `codex exec`, Codex's own harness, for comparison."""
    reply = workspace.parent / "codex-reply.txt"
    command = [
        "codex", "exec", "--json", "--ephemeral", "--ignore-user-config", "--skip-git-repo-check",
        "-m", model, "-c", f'model_reasoning_effort="{CODEX_EFFORT}"',
        "--sandbox", "workspace-write", "-C", str(workspace),
        "-o", str(reply), task.prompt,
    ]  # fmt: skip
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        limit=MAX_LINE_BYTES,
    )
    assert process.stdout is not None
    started = time.monotonic()
    try:
        async with asyncio.timeout(task.timeout_s):
            async for raw in process.stdout:
                with suppress(json.JSONDecodeError):
                    tally_codex(outcome, json.loads(raw))
            await process.wait()
    except TimeoutError:
        outcome.status = "timeout"
        process.kill()
        await process.wait()
    outcome.seconds = round(time.monotonic() - started, 1)
    if outcome.status == "ran" and process.returncode != 0:
        outcome.status = "error"
        outcome.detail = outcome.detail or f"codex exited with {process.returncode}"
    return reply.read_text() if reply.exists() else ""


def keep(folder: Path, task: Task, number: int) -> None:
    """The run's trace (the session database, with its spans) and the raw logs of a native
    harness, kept beside the results so they can be read afterwards."""
    if kept is None:
        return
    name = f"{task.id}-{number}"
    for database in (folder / "data" / "sessions").glob("*.db"):
        shutil.copy(database, kept / f"{name}.db")
    for log in folder.glob("*.jsonl"):
        shutil.copy(log, kept / f"{name}.{log.name}")
    reply = folder / "reply.txt"
    if reply.exists():
        shutil.copy(reply, kept / f"{name}.reply.txt")


Native = Callable[[Task, Path, str, Outcome], Coroutine[Any, Any, str]]
NATIVE: dict[str, Native] = {}


async def stream_native(
    command: list[str], workspace: Path, timeout_s: int, log: Path, outcome: Outcome
) -> AsyncIterator[dict[str, Any]]:
    """A native harness's JSON lines, written to `log` as they come; a timeout kills it."""
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=workspace,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        limit=MAX_LINE_BYTES,
    )
    assert process.stdout is not None
    # A deadline per line: a timeout around a generator that yields does not reach its reads.
    deadline = time.monotonic() + timeout_s
    with log.open("wb") as written:
        while True:
            left = deadline - time.monotonic()
            try:
                raw = await asyncio.wait_for(process.stdout.readline(), max(left, 0.01))
            except TimeoutError:
                outcome.status = "timeout"
                process.kill()
                await process.wait()
                return
            if not raw:
                break
            written.write(raw)
            written.flush()
            with suppress(json.JSONDecodeError):
                decoded = json.loads(raw)
                if isinstance(decoded, dict):
                    yield decoded
    await process.wait()
    if outcome.status == "ran" and process.returncode not in (0, None):
        outcome.detail = outcome.detail or f"exited with {process.returncode}"


async def drive_claude(task: Task, workspace: Path, model: str, outcome: Outcome) -> str:
    """The task through `claude -p`, Claude Code's own harness: its tools, sandboxed to the
    workspace, without the user's CLAUDE.md, skills, plugins, hooks or MCP servers."""
    command = [
        "claude", "-p", task.prompt, "--output-format", "stream-json", "--verbose",
        "--model", model, "--safe-mode", "--permission-mode", "acceptEdits",
        "--settings", json.dumps({"sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True}}),
    ]  # fmt: skip
    started = time.monotonic()
    reply = ""
    log = workspace.parent / "claude.jsonl"
    async for event in stream_native(command, workspace, task.timeout_s, log, outcome):
        kind = event.get("type")
        if kind == "assistant":
            outcome.model_turns += 1
            blocks: list[dict[str, Any]] = event["message"].get("content") or []
            for block in blocks:
                if block.get("type") == "tool_use":
                    outcome.tool_calls += 1
                    name = block.get("name", "tool")
                    outcome.tools[name] = outcome.tools.get(name, 0) + 1
                elif block.get("type") == "text" and block.get("text"):
                    reply = block["text"]
        elif kind == "user":
            message: dict[str, Any] = event.get("message") or {}
            results: list[Any] = message.get("content") or []
            for result in results:
                if isinstance(result, dict) and cast("dict[str, Any]", result).get("is_error"):
                    outcome.tool_errors += 1
        elif kind == "result":
            usage: dict[str, int] = event.get("usage") or {}
            outcome.input_tokens = usage.get("input_tokens", 0)
            outcome.cache_read_tokens = usage.get("cache_read_input_tokens", 0)
            outcome.cache_write_tokens = usage.get("cache_creation_input_tokens", 0)
            outcome.output_tokens = usage.get("output_tokens", 0)
            outcome.status = "failed" if event.get("is_error") else "ran"
            if event.get("is_error"):
                outcome.detail = str(event.get("result"))[:300]
            reply = str(event.get("result") or reply)
    outcome.seconds = round(time.monotonic() - started, 1)
    return reply


async def drive_grok(task: Task, workspace: Path, model: str, outcome: Outcome) -> str:
    """The task through `grok -p`, Grok Build's own harness, sandboxed to the workspace."""
    command = [
        "grok", "-p", task.prompt, "--output-format", "streaming-json", "-m", model,
        "--sandbox", "workspace", "--permission-mode", "bypassPermissions",
        "--no-subagents", "--disable-web-search", "--cwd", str(workspace),
    ]  # fmt: skip
    started = time.monotonic()
    text: list[str] = []
    log = workspace.parent / "grok.jsonl"
    async for event in stream_native(command, workspace, task.timeout_s, log, outcome):
        kind = event.get("type")
        if kind == "text":
            text.append(str(event.get("data") or ""))
        elif kind == "usage":
            outcome.model_turns += 1
            usage: dict[str, int] = event.get("usage") or {}
            # Grok's input tokens leave out the part read from the cache.
            cached = usage.get("cache_read_input_tokens", 0)
            outcome.input_tokens += usage.get("input_tokens", 0)
            outcome.cache_read_tokens += cached
            outcome.cache_write_tokens += usage.get("cache_creation_input_tokens", 0)
            outcome.output_tokens += usage.get("output_tokens", 0)
            # Each request's own prompt; the largest is the context's peak.
            outcome.context_peak = max(outcome.context_peak, usage.get("input_tokens", 0) + cached)
            outcome.status = "ran"
        elif kind == "tool_call":
            outcome.tool_calls += 1
            name = str(event.get("toolName") or "tool")
            outcome.tools[name] = outcome.tools.get(name, 0) + 1
            text.clear()
        elif kind == "tool_call_update" and event.get("status") == "failed":
            outcome.tool_errors += 1
        elif kind == "error":
            outcome.status = "failed"
            outcome.detail = str(event.get("message"))[:300]
    outcome.seconds = round(time.monotonic() - started, 1)
    return "".join(text)


async def drive_pi(task: Task, workspace: Path, model: str, outcome: Outcome) -> str:
    """The task through `pi -p`, pi's own harness, on a local OpenAI-compatible server (--base-url,
    Ollama's by default): pi gets a config folder of its own that knows only that endpoint, and no
    extensions, skills, prompt templates or context files. Its tools run in the task's folder, as
    Plural's do in auto mode."""
    agent = workspace.parent / "pi-agent"
    agent.mkdir(exist_ok=True)
    name = model.removeprefix("ollama/")
    (agent / "models.json").write_text(
        json.dumps(
            {
                "providers": {
                    "ollama": {
                        "baseUrl": base_url or "http://localhost:11434/v1",
                        "api": "openai-completions",
                        "apiKey": "ollama",
                        "models": [{"id": name, "contextWindow": 131072}],
                    }
                }
            }
        )
    )
    command = [
        "pi", "-p", task.prompt, "--model", f"ollama/{name}", "--mode", "json",
        "--no-session", "--no-extensions", "--no-skills", "--no-context-files",
        "--no-prompt-templates", "--offline",
    ]  # fmt: skip
    os.environ["PI_CODING_AGENT_DIR"] = str(agent)
    started = time.monotonic()
    reply = ""
    log = workspace.parent / "pi.jsonl"
    try:
        async for event in stream_native(command, workspace, task.timeout_s, log, outcome):
            kind = event.get("type")
            message: dict[str, Any] = event.get("message") or {}
            if kind == "message_end" and message.get("role") == "assistant":
                outcome.model_turns += 1
                usage: dict[str, int] = message.get("usage") or {}
                outcome.input_tokens += usage.get("input", 0)
                outcome.cache_read_tokens += usage.get("cacheRead", 0)
                outcome.cache_write_tokens += usage.get("cacheWrite", 0)
                outcome.output_tokens += usage.get("output", 0)
                prompt = usage.get("input", 0) + usage.get("cacheRead", 0)
                outcome.context_peak = max(outcome.context_peak, prompt)
                parts: list[dict[str, Any]] = message.get("content") or []
                text = "".join(str(p.get("text", "")) for p in parts if p.get("type") == "text")
                if text:
                    reply = text
            elif kind == "tool_execution_end":
                outcome.tool_calls += 1
                tool = str(event.get("toolName") or "tool")
                outcome.tools[tool] = outcome.tools.get(tool, 0) + 1
                if event.get("isError"):
                    outcome.tool_errors += 1
            elif kind == "agent_end" and outcome.status != "timeout":
                outcome.status = "ran"
    finally:
        os.environ.pop("PI_CODING_AGENT_DIR", None)
    outcome.seconds = round(time.monotonic() - started, 1)
    return reply


NATIVE.update(codex=drive_codex, claude=drive_claude, grok=drive_grok, pi=drive_pi)


async def run_task(
    task: Task, harness: str, preset: str, model: str, gate: asyncio.Semaphore, number: int = 0
) -> Outcome:
    outcome = Outcome(task=task.id)
    async with gate:
        with tempfile.TemporaryDirectory(prefix="plural-eval-") as folder:
            try:
                settings = await asyncio.to_thread(begin, task, folder, preset, model)
                if harness in NATIVE:
                    reply = await NATIVE[harness](task, settings.workspace, model, outcome)
                else:
                    reply = await drive(task, settings, outcome)
                await asyncio.to_thread(judge, task, settings.workspace, outcome, reply)
            except Exception as error:  # one broken task must not end the others
                outcome.status = "error"
                outcome.detail = f"{type(error).__name__}: {error}"
            with suppress(OSError):
                keep(Path(folder), task, number)
    print(line(outcome), flush=True)
    return outcome


def line(outcome: Outcome) -> str:
    tokens = outcome.input_tokens + outcome.cache_read_tokens + outcome.cache_write_tokens
    return (
        f"{outcome.task:26} {outcome.status:8} {outcome.seconds:7.1f}s "
        f"{outcome.model_turns:3} turns {outcome.tool_calls:3} tools "
        f"{outcome.tool_errors:2} failed {tokens:8} in {outcome.output_tokens:7} out "
        f"ctx {outcome.context_peak:7}/{outcome.context_window} "
        f"{outcome.compactions} compactions"
        + (f"  {outcome.detail.splitlines()[-1][:80]}" if outcome.detail else "")
    )


def summary(outcomes: list[Outcome]) -> dict[str, float]:
    judged = [outcome for outcome in outcomes if outcome.status != "error"]
    passed = sum(outcome.status == "passed" for outcome in judged)
    count = max(len(judged), 1)
    prompt = sum(o.input_tokens + o.cache_read_tokens + o.cache_write_tokens for o in judged)
    return {
        "judged": len(judged),
        "broken_runs": len(outcomes) - len(judged),
        "passed": passed,
        "pass_rate": round(passed / count, 3),
        "seconds_per_task": round(sum(o.seconds for o in judged) / count, 1),
        "turns_per_task": round(sum(o.model_turns for o in judged) / count, 1),
        "tools_per_task": round(sum(o.tool_calls for o in judged) / count, 1),
        "tool_error_rate": round(
            sum(o.tool_errors for o in judged) / max(sum(o.tool_calls for o in judged), 1), 3
        ),
        "prompt_tokens": prompt,
        "output_tokens": sum(o.output_tokens for o in judged),
        "cache_hit": round(sum(o.cache_read_tokens for o in judged) / max(prompt, 1), 3),
        "context_peak": max((o.context_peak for o in judged), default=0),
        "compactions": sum(o.compactions for o in judged),
    }


def spent_on(outcomes: list[Outcome]) -> dict[str, int]:
    """What filled the context at each task's peak, added up and largest first."""
    parts: dict[str, int] = {}
    for outcome in outcomes:
        for name, tokens in outcome.context_parts.items():
            parts[name] = parts.get(name, 0) + tokens
    return dict(sorted(parts.items(), key=lambda part: -part[1]))


def compare(now: dict[str, float], path: Path) -> None:
    before = json.loads(path.read_text())["summary"]
    print(f"\nagainst {path.name}:")
    for key, value in now.items():
        print(f"  {key:18} {before.get(key, 0):>12} -> {value}")


def current_agent() -> tuple[str, str]:
    """What the plural window is set to use."""
    settings = json.loads((Path.home() / ".plural" / "tui.json").read_text())
    return settings["agent"]["preset"], settings["agent"]["model"]


async def run(args: argparse.Namespace, preset: str, model: str) -> list[Outcome]:
    gate = asyncio.Semaphore(args.jobs)
    tasks = load_tasks(args.task) * args.repeat
    runs = (
        run_task(task, args.harness, preset, model, gate, number)
        for number, task in enumerate(tasks)
    )
    return list(await asyncio.gather(*runs))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--harness",
        choices=["plural", "codex", "claude", "grok", "pi"],
        default="plural",
        help="codex runs the same tasks through codex exec instead, with the same model",
    )
    parser.add_argument("--preset", help="default: the plural window's agent")
    parser.add_argument("--model", help="default: the plural window's agent")
    parser.add_argument("--task", action="append", help="only this task; can repeat")
    parser.add_argument("--repeat", type=int, default=1, help="runs of each task")
    parser.add_argument("--jobs", type=int, default=2, help="tasks at once")
    parser.add_argument(
        "--keep-home",
        action="store_true",
        help="let your own skills and agents into the runs; the numbers then are yours alone",
    )
    parser.add_argument("--compare", type=Path, help="an earlier results file")
    parser.add_argument(
        "--base-url",
        help="an OpenAI-compatible endpoint in place of the preset's, for a local server",
    )
    parser.add_argument("--list", action="store_true", help="print the tasks and stop")
    args = parser.parse_args()
    if args.list:
        for task in load_tasks(args.task):
            print(task.id)
        return 0
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.ERROR))
    if args.preset and args.model:
        preset, model = args.preset, args.model
    else:
        fallback_preset, fallback_model = current_agent()
        preset = args.preset or fallback_preset
        model = args.model or fallback_model
    print(f"{args.harness} · {preset} · {model}", flush=True)
    global kept, base_url
    base_url = args.base_url
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    kept = RESULTS / f"{stamp}-{args.harness}-{model.replace('/', '_')}"
    kept.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="plural-eval-home-") as home:
        if not args.keep_home:
            # Skills, agents, MCP servers and plugins in the home folder go into every prompt of
            # the host, which runs in this process: it alone gets an empty home. The CLIs it starts
            # and the native harnesses keep the real one, where their sign-ins live.
            clean = Path(home)
            Path.home = classmethod(lambda cls: cls(clean))  # type: ignore[method-assign]
        outcomes = asyncio.run(run(args, preset, model))
    totals = summary(outcomes)
    print("\n" + json.dumps({**totals, "context_at_peak": spent_on(outcomes)}, indent=2))
    path = kept / "results.json"
    report = {
        "harness": args.harness,
        "preset": preset,
        "model": model,
        "at": stamp,
        "commit": subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False
        ).stdout.strip(),
        "summary": totals,
        "context_at_peak": spent_on(outcomes),
        "tasks": [asdict(outcome) for outcome in outcomes],
    }
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"\n{path}")
    if args.compare:
        compare(totals, args.compare)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
