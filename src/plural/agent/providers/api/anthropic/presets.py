"""Providers reached through the Anthropic Messages API adapter."""

from typing import Final

from plural.agent.providers.preset import Preset

PRESETS: Final[tuple[Preset, ...]] = (
    Preset(
        id="anthropic",
        label="Anthropic",
        adapter="anthropic",
        needs_key=True,
        models=("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"),
        hint="Claude models with an Anthropic API key",
        key_env=("ANTHROPIC_API_KEY",),
    ),
    Preset(
        id="anthropic_oauth",
        label="Claude OAuth",
        adapter="anthropic_oauth",
        models=(
            "claude-haiku-4-5-20251001",
            "claude-haiku-5-5",
            "claude-sonnet-5-5",
            "claude-opus-5-5",
            "claude-fable-5-1",
            "claude-opus-5",
            "claude-sonnet-5",
            "claude-fable-5",
            "claude-opus-4-8",
            "claude-opus-4-7",
            "claude-sonnet-4-6",
            "claude-opus-4-6",
            "claude-opus-4-5-20251101",
            "claude-sonnet-4-5-20250929",
        ),
        hint="Claude model IDs; Test connection checks access for your account",
        connection="oauth",
    ),
    Preset(
        id="minimax",
        label="MiniMax",
        adapter="anthropic",
        base_url="https://api.minimax.io/anthropic",
        needs_key=True,
        models=("MiniMax-M2.7",),
        hint="Anthropic-compatible Messages API",
    ),
    Preset(
        id="minimax_cn",
        label="MiniMax China",
        adapter="anthropic",
        base_url="https://api.minimaxi.com/anthropic",
        needs_key=True,
        models=("MiniMax-M2.7",),
        hint="Anthropic-compatible Messages API",
    ),
    Preset(
        id="vercel_ai_gateway",
        label="Vercel AI Gateway",
        adapter="anthropic",
        base_url="https://ai-gateway.vercel.sh",
        needs_key=True,
        hint="Anthropic-compatible Messages API; enter a model route",
    ),
)
