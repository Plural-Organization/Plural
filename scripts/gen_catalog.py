"""Writes the provider catalog the terminal client renders, from plural.agent.providers.catalog."""

import json
import sys
from pathlib import Path

from plural.agent.providers.catalog import PRESETS

OUTPUT = Path(__file__).resolve().parents[1] / "tui" / "src" / "catalog.json"


def render() -> str:
    return json.dumps([preset.to_json() for preset in PRESETS], indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    text = render()
    if "--check" in sys.argv:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != text:
            print("provider catalog is stale: run scripts/gen_catalog.py", file=sys.stderr)
            return 1
        return 0
    OUTPUT.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
