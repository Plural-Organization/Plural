import json
import sys
from pathlib import Path

from pydantic import BaseModel

from plural.protocol.commands import Command
from plural.protocol.envelope import Envelope
from plural.protocol.events import Event, EventRecord

OUTPUT = Path(__file__).resolve().parents[1] / "web" / "src" / "protocol" / "schema.json"


class PluralProtocol(BaseModel):
    envelope: Envelope
    command: Command
    event: Event
    record: EventRecord


def render() -> str:
    return json.dumps(PluralProtocol.model_json_schema(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    schema = render()
    if "--check" in sys.argv:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != schema:
            print("protocol schema is stale: run scripts/gen_schema.py", file=sys.stderr)
            return 1
        return 0
    OUTPUT.write_text(schema, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
