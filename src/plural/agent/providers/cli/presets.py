"""Providers that run an installed agent CLI with its own sign-in."""

from typing import Final

from plural.agent.providers.preset import Preset

PRESETS: Final[tuple[Preset, ...]] = (
    Preset(
        id="claude_code",
        label="Claude Code",
        adapter="claude_code",
        models=(
            "claude-sonnet-5-5",
            "claude-opus-5-5",
            "claude-haiku-5-5",
            "claude-fable-5-1",
            "claude-sonnet-5",
            "claude-opus-5",
            "claude-fable-5",
            "claude-opus-4-8",
            "claude-opus-4-7",
            "claude-sonnet-4-6",
            "claude-opus-4-6",
            "claude-opus-4-5-20251101",
            "claude-haiku-4-5-20251001",
            "claude-sonnet-4-5-20250929",
        ),
        hint="Uses the installed Claude Code CLI; sign in with claude auth login",
        connection="oauth",
    ),
    Preset(
        id="codex_cli",
        label="Codex CLI",
        adapter="codex_cli",
        models=("gpt-6.1-sol", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna", "gpt-5.6-sol", "gpt-5.5"),
        hint="Streams replies from Codex CLI and keeps one session for this room",
        connection="oauth",
    ),
)
