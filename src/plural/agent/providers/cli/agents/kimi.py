from pathlib import Path

from plural.agent.providers.cli.agents.base import Call
from plural.agent.providers.cli.agents.claude_stream import ClaudeStreamCli


class KimiCliProvider(ClaudeStreamCli):
    adapter = "kimi_cli"
    label = "Kimi CLI"
    binary = "kimi"
    install = "see moonshotai.github.io/kimi-code"
    login = "run kimi once and use /login"

    def command(self, prompt: str, run_dir: Path) -> Call:
        # Without --yolo it asks before its own tools, and prompt mode cannot answer.
        return Call([*self.model_flag("-m"), "-p", prompt, "--output-format", "stream-json"])
