"""Models behind an installed agent CLI, each signed in with the CLI's own account.

Every CLI is a `CliProvider` in a module of its own. Claude Code and Codex speak their own
protocols; the rest get the request as one prompt and answer in JSON (`PromptCliProvider`).
"""

from typing import Final

from plural.agent.providers.cli.amp import AmpCliProvider
from plural.agent.providers.cli.base import CliProvider
from plural.agent.providers.cli.claude_code import ClaudeCodeProvider
from plural.agent.providers.cli.codex import CodexCliProvider
from plural.agent.providers.cli.copilot import CopilotCliProvider
from plural.agent.providers.cli.cursor import CursorCliProvider
from plural.agent.providers.cli.gemini import GeminiCliProvider
from plural.agent.providers.cli.grok import GrokCliProvider
from plural.agent.providers.cli.kimi import KimiCliProvider
from plural.agent.providers.cli.opencode import OpencodeCliProvider
from plural.agent.providers.cli.qwen import QwenCliProvider
from plural.agent.providers.preset import Preset

CLI_PROVIDERS: Final[dict[str, type[CliProvider]]] = {
    provider.adapter: provider
    for provider in (
        ClaudeCodeProvider,
        CodexCliProvider,
        GeminiCliProvider,
        QwenCliProvider,
        CopilotCliProvider,
        CursorCliProvider,
        KimiCliProvider,
        GrokCliProvider,
        AmpCliProvider,
        OpencodeCliProvider,
    )
}

PRESETS: Final[tuple[Preset, ...]] = tuple(provider.preset() for provider in CLI_PROVIDERS.values())

__all__ = ["CLI_PROVIDERS", "PRESETS", "CliProvider"]
