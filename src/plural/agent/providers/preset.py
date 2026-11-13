"""A provider the host can run: which adapter, where, which models, and where its key lives."""

from dataclasses import asdict, dataclass
from typing import Final, Literal, get_args

# Models behind an installed agent CLI (providers/cli/), signed in with the CLI's own account.
CliAdapter = Literal[
    "claude_code",
    "codex_cli",
    "gemini_cli",
    "qwen_cli",
    "copilot_cli",
    "cursor_cli",
    "kimi_cli",
    "grok_cli",
    "amp_cli",
    "opencode_cli",
]
CLI_ADAPTERS: Final[tuple[CliAdapter, ...]] = get_args(CliAdapter)
Adapter = Literal["fake", "anthropic", "anthropic_oauth", "openai"] | CliAdapter
Connection = Literal["api_key", "oauth", "local"]


@dataclass(frozen=True, slots=True)
class Preset:
    id: str
    label: str
    adapter: Adapter
    hint: str
    base_url: str = ""
    needs_key: bool = False
    editable_url: bool = False
    context_window: bool = False
    models: tuple[str, ...] = ()
    connection: Connection = "api_key"
    key_env: tuple[str, ...] = ()

    def to_json(self) -> dict[str, object]:
        """The client's shape of a preset (camelCase, as tui/src/catalog.json holds it)."""
        data = asdict(self)
        return {
            "id": data["id"],
            "label": data["label"],
            "provider": data["adapter"],
            "baseUrl": data["base_url"],
            "needsKey": data["needs_key"],
            "editableUrl": data["editable_url"],
            "contextWindow": data["context_window"],
            "models": list(data["models"]),
            "hint": data["hint"],
            "connection": data["connection"],
            "keyEnv": list(data["key_env"]),
        }
