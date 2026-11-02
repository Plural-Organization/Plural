"""Entry point of the frozen host. `--frozen-selftest` checks the bundle is complete."""

import importlib
import sys

SELFTEST_MODULES = (
    "anthropic",
    "openai",
    "pydantic_ai.models.anthropic",
    "pydantic_ai.models.openai",
    "plural.host.providers",
)


def selftest() -> int:
    for module in SELFTEST_MODULES:
        importlib.import_module(module)
    from plural.host.extras import is_installed

    if not (is_installed("anthropic") and is_installed("openai")):
        print("frozen host is missing a model SDK", file=sys.stderr)
        return 1
    print("frozen host ok")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--frozen-selftest"]:
        raise SystemExit(selftest())
    from plural.cli.main import app

    app()
