"""Where a run's tokens and time went, from the traces and logs an eval keeps.

    uv run python -m benchmarks.evals.analyze benchmarks/results/<run> [<run> ...]

For Plural runs it reads the spans in each task's session database; for native harnesses the
JSON lines they printed. It prints one line per run and, with --tasks, one per task.
"""

import argparse
import json
import sqlite3
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class Calls:
    """What the model calls of one task cost."""

    task: str
    status: str = ""
    seconds: float = 0
    calls: int = 0
    # Every prompt token sent, and each call's own prompt.
    prompt: int = 0
    prompts: list[int] = field(default_factory=list[int])
    output: int = 0
    cached: int = 0
    model_ms: int = 0
    tool_ms: int = 0
    wait_ms: int = 0
    tools: int = 0
    tool_errors: int = 0
    # Model calls that gave nothing back: no text and no tool call.
    empty: int = 0
    first_ms: list[int] = field(default_factory=list[int])
    errors: list[str] = field(default_factory=list[str])


def plural_task(database: Path, outcome: dict[str, Any]) -> Calls:
    calls = Calls(task=outcome["task"], status=outcome["status"], seconds=outcome["seconds"])
    connection = sqlite3.connect(database)
    try:
        rows = connection.execute("SELECT payload FROM spans").fetchall()
    except sqlite3.OperationalError:
        rows = []
    connection.close()
    for (payload,) in rows:
        span = json.loads(payload)
        took = (span["ended_ms"] or span["started_ms"]) - span["started_ms"]
        usage = span["usage"]
        if span["kind"] == "llm":
            prompt = (
                usage["input_tokens"] + usage["cache_read_tokens"] + usage["cache_write_tokens"]
            )
            calls.calls += 1
            calls.prompt += prompt
            calls.prompts.append(span["context_tokens"] or prompt)
            calls.output += usage["output_tokens"]
            calls.cached += usage["cache_read_tokens"]
            calls.model_ms += took
            if span["first_ms"] is not None:
                calls.first_ms.append(span["first_ms"])
            answer: dict[str, Any] = json.loads(span["output"]) if span["output"] else {}
            if not answer.get("text") and not answer.get("tool_calls"):
                calls.empty += 1
        elif span["kind"] in ("tool", "agent"):
            calls.tools += 1
            calls.tool_ms += took
            if span["status"] in ("error", "denied"):
                calls.tool_errors += 1
                calls.errors.append(f"{span['name']}: {span['error'][:120]}")
        elif span["kind"] == "approval":
            calls.wait_ms += took
    return calls


def native_task(log: Path, outcome: dict[str, Any]) -> Calls:
    """A native harness's own log: Claude Code's messages, Grok's requests or Codex's turns."""
    calls = Calls(task=outcome["task"], status=outcome["status"], seconds=outcome["seconds"])
    seen: set[str] = set()
    for raw in log.read_text(errors="replace").splitlines():
        try:
            event: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        usage: dict[str, int] | None = None
        if kind == "assistant":
            message: dict[str, Any] = event.get("message") or {}
            identity = str(message.get("id"))
            if identity in seen:
                continue
            seen.add(identity)
            usage = message.get("usage")
        elif kind == "usage":
            usage = event.get("usage")

        if usage:
            prompt = (
                usage.get("input_tokens", 0)
                + usage.get("cache_read_input_tokens", 0)
                + usage.get("cache_creation_input_tokens", 0)
            )
            calls.calls += 1
            calls.prompt += prompt
            calls.prompts.append(prompt)
            calls.output += usage.get("output_tokens", 0)
            calls.cached += usage.get("cache_read_input_tokens", 0)
    calls.tools = outcome["tool_calls"]
    calls.tool_errors = outcome["tool_errors"]
    # Streamed messages carry a partial count of their output; the run's own total is right.
    calls.output = outcome["output_tokens"] or calls.output
    if calls.calls == 0:
        # Codex reports a turn's total only.
        calls.prompt = outcome["input_tokens"] + outcome["cache_read_tokens"]
        calls.output = outcome["output_tokens"]
        calls.cached = outcome["cache_read_tokens"]
    return calls


def load(run: Path) -> tuple[dict[str, Any], list[Calls]]:
    report = json.loads((run / "results.json").read_text())
    tasks: list[Calls] = []
    for number, outcome in enumerate(report["tasks"]):
        name = f"{outcome['task']}-{number}"
        database = run / f"{name}.db"
        logs = sorted(run.glob(f"{name}.*.jsonl"))
        if database.exists():
            tasks.append(plural_task(database, outcome))
        elif logs:
            tasks.append(native_task(logs[0], outcome))
        else:
            # Codex reports a turn's total only, in the results themselves.
            calls = Calls(
                task=outcome["task"], status=outcome["status"], seconds=outcome["seconds"]
            )
            calls.prompt = outcome["input_tokens"] + outcome["cache_read_tokens"]
            calls.output = outcome["output_tokens"]
            calls.cached = outcome["cache_read_tokens"]
            calls.tools = outcome["tool_calls"]
            calls.tool_errors = outcome["tool_errors"]
            tasks.append(calls)
    return report, tasks


def mean(values: list[int] | list[float]) -> float:
    return statistics.fmean(values) if values else 0


def row(report: dict[str, Any], tasks: list[Calls]) -> str:
    judged = [task for task in tasks if task.status != "error"]
    passed = sum(task.status == "passed" for task in judged)
    calls = sum(task.calls for task in judged)
    prompt = sum(task.prompt for task in judged)
    per_call = [p for task in judged for p in task.prompts]
    return (
        f"{report['harness']:7} {report['model']:20} "
        f"{passed:2}/{len(judged):<2} "
        f"{mean([t.seconds for t in judged]):6.1f}s "
        f"{calls / max(len(judged), 1):5.1f} calls "
        f"{prompt / max(len(judged), 1) / 1000:6.1f}k in/task "
        f"{mean(per_call) / 1000:5.1f}k in/call "
        f"{sum(t.output for t in judged) / max(len(judged), 1):6.0f} out/task "
        f"{sum(t.cached for t in judged) / max(prompt, 1):4.0%} cached "
        f"{sum(t.tool_errors for t in judged)}/{sum(t.tools for t in judged)} tool errors "
        f"{sum(t.empty for t in judged)} empty"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--tasks", action="store_true", help="a line per task too")
    parser.add_argument("--errors", action="store_true", help="the tool errors of each task")
    args = parser.parse_args()
    for run in args.runs:
        report, tasks = load(run)
        print(row(report, tasks))
        for task in tasks if args.tasks or args.errors else []:
            if args.tasks:
                print(
                    f"    {task.task:24} {task.status:7} {task.seconds:6.1f}s {task.calls:3} calls "
                    f"{task.prompt / 1000:6.1f}k in {task.output:6} out "
                    f"model {task.model_ms / 1000:5.1f}s tools {task.tool_ms / 1000:5.1f}s "
                    f"{task.tool_errors}/{task.tools} err"
                )
            for error in task.errors if args.errors else []:
                print(f"        ✕ {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
