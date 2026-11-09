"""Agent CLIs used as model backends, one subclass of `AgentCliProvider` each."""

from typing import Final

from plural.agent.providers.cli.agents.amp import AmpCliProvider
from plural.agent.providers.cli.agents.base import AgentCliProvider
from plural.agent.providers.cli.agents.copilot import CopilotCliProvider
from plural.agent.providers.cli.agents.cursor import CursorCliProvider
from plural.agent.providers.cli.agents.gemini import GeminiCliProvider
from plural.agent.providers.cli.agents.grok import GrokCliProvider
from plural.agent.providers.cli.agents.kimi import KimiCliProvider
from plural.agent.providers.cli.agents.opencode import OpencodeCliProvider
from plural.agent.providers.cli.agents.qwen import QwenCliProvider
from plural.agent.providers.preset import AgentCliAdapter

AGENT_CLIS: Final[dict[AgentCliAdapter, type[AgentCliProvider]]] = {
    provider.adapter: provider
    for provider in (
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

__all__ = ["AGENT_CLIS", "AgentCliProvider"]
