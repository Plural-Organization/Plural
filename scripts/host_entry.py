"""Entry point of the frozen host. `--frozen-selftest` checks the bundle is complete."""

import importlib
import os
import ssl
import sys
from importlib import resources

SELFTEST_MODULES = (
    "anthropic",
    "openai",
    "pydantic_ai.models.anthropic",
    "pydantic_ai.models.openai",
    "plural.host.providers",
    "plural.agent.agents",
)


# Files the host reads at run time. --collect-submodules gathers code only, so each kind of data
# file is checked here, and the built-in agents are loaded by importing the module that reads them.
SELFTEST_DATA = (
    ("plural.agent", "builtin_agents/explore.md"),
    ("plural.agent", "builtin_skills/plural-plugins/SKILL.md"),
    ("plural.agent.prompts", "system.md"),
    ("plural.storage.migrations", "0001_init.sql"),
)


def use_bundled_certificates() -> None:
    """The frozen OpenSSL looks for certificates where its build machine kept them, so every https
    and wss relay failed with "cannot reach the relay". Point it at the bundled certifi instead."""
    if os.environ.get("SSL_CERT_FILE"):
        return
    try:
        import certifi
    except ImportError:
        return
    os.environ["SSL_CERT_FILE"] = certifi.where()


def selftest() -> int:
    for module in SELFTEST_MODULES:
        importlib.import_module(module)
    for package, name in SELFTEST_DATA:
        if not resources.files(package).joinpath(name).is_file():
            print(f"frozen host is missing {package}/{name}", file=sys.stderr)
            return 1
    from plural.host.extras import is_installed

    if not (is_installed("anthropic") and is_installed("openai")):
        print("frozen host is missing a model SDK", file=sys.stderr)
        return 1
    if not ssl.create_default_context().get_ca_certs():
        print("frozen host has no certificates to check https with", file=sys.stderr)
        return 1
    print("frozen host ok")
    return 0


if __name__ == "__main__":
    use_bundled_certificates()
    if sys.argv[1:] == ["--frozen-selftest"]:
        raise SystemExit(selftest())
    from plural.cli.main import app

    app()
