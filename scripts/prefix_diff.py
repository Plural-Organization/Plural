"""Show where requests saved with PLURAL_DUMP_REQUESTS=1 stop sharing their beginning.

A provider's prompt cache serves only the part of a request that matches an earlier one from
the start, in the order tools, system, messages. Anything that changes earlier than the end of
the previous request makes the rest of it full price again.

    uv run python scripts/prefix_diff.py ~/.plural/logs/requests/<room>
    uv run python scripts/prefix_diff.py a.json b.json

With a folder, each request is compared with the one before it. Requests for a summary, a
briefing or an answer to a plugin are compared only with requests of their own kind.

The requests are what Plural hands its provider adapter; a CLI provider (claude_code,
codex_cli) reshapes them before they reach the model.
"""

import json
import sys
from pathlib import Path
from typing import Any

SNIPPET = 60


def _purpose(path: Path) -> str:
    return path.stem.partition("-")[2] or "turn"


def _first_difference(old: str, new: str) -> int:
    for index, (a, b) in enumerate(zip(old, new, strict=False)):
        if a != b:
            return index
    return min(len(old), len(new))


def _tool_names(request: dict[str, Any]) -> list[str]:
    return [tool["name"] for tool in request.get("tools", [])]


def _show(text: str, at: int) -> str:
    piece = text[max(0, at - 20) : at + SNIPPET].replace("\n", "\\n")
    return repr(piece)


def compare(old: dict[str, Any], new: dict[str, Any]) -> str:
    """One line on where `new` stops repeating `old`, or that it extends it."""
    old_tools = json.dumps(old.get("tools", []), sort_keys=True)
    new_tools = json.dumps(new.get("tools", []), sort_keys=True)
    if old_tools != new_tools:
        return f"tools changed: {_tool_names(old)} -> {_tool_names(new)}"
    if old["system"] != new["system"]:
        at = _first_difference(old["system"], new["system"])
        return f"system changed at character {at}: {_show(new['system'], at)}"
    old_messages, new_messages = old["messages"], new["messages"]
    for index, (a, b) in enumerate(zip(old_messages, new_messages, strict=False)):
        if a == b:
            continue
        where = f"message {index} ({b.get('role')})"
        if a.get("content") != b.get("content"):
            at = _first_difference(a.get("content", ""), b.get("content", ""))
            return f"{where} changed at character {at}: {_show(b.get('content', ''), at)}"
        fields = sorted(key for key in a.keys() | b.keys() if a.get(key) != b.get(key))
        return f"{where} changed in {', '.join(fields)}"
    if len(new_messages) < len(old_messages):
        return f"messages dropped: {len(old_messages)} -> {len(new_messages)}"
    return f"extends the previous request (+{len(new_messages) - len(old_messages)} messages)"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main(arguments: list[str]) -> int:
    if len(arguments) == 2:
        print(compare(_load(Path(arguments[0])), _load(Path(arguments[1]))))
        return 0
    if len(arguments) != 1 or not Path(arguments[0]).is_dir():
        print(__doc__, file=sys.stderr)
        return 2
    previous: dict[str, Path] = {}
    for path in sorted(Path(arguments[0]).glob("*.json")):
        purpose = _purpose(path)
        if purpose in previous:
            print(f"{path.name}: {compare(_load(previous[purpose]), _load(path))}")
        else:
            print(f"{path.name}: first {purpose} request")
        previous[purpose] = path
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
