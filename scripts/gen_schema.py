import json
import sys
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from plural.protocol.commands import Command
from plural.protocol.envelope import Envelope
from plural.protocol.events import Event, EventRecord

OUTPUT = Path(__file__).resolve().parents[1] / "client" / "src" / "protocol"


class Outbound(BaseModel):
    envelope: Envelope
    event: Event
    record: EventRecord


class Inbound(BaseModel):
    command: Command


def _strip_titles(node: object, *, names: bool = False) -> object:
    if isinstance(node, dict):
        mapping = cast("dict[str, object]", node)
        return {
            key: _strip_titles(value, names=key in {"properties", "$defs"})
            for key, value in mapping.items()
            if names or key != "title"
        }
    if isinstance(node, list):
        return [_strip_titles(item) for item in cast("list[object]", node)]
    return node


def _dump(schema: dict[str, Any]) -> str:
    return json.dumps(_strip_titles(schema), indent=2, sort_keys=True) + "\n"


def render() -> dict[str, str]:
    return {
        "events.schema.json": _dump(Outbound.model_json_schema(mode="serialization")),
        "commands.schema.json": _dump(Inbound.model_json_schema(mode="validation")),
    }


def main() -> int:
    rendered = render()
    if "--check" in sys.argv:
        stale = [
            name
            for name, text in rendered.items()
            if not (OUTPUT / name).exists() or (OUTPUT / name).read_text(encoding="utf-8") != text
        ]
        if stale:
            print(
                f"protocol schema is stale ({', '.join(stale)}): run scripts/gen_schema.py",
                file=sys.stderr,
            )
            return 1
        return 0
    for name, text in rendered.items():
        (OUTPUT / name).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
