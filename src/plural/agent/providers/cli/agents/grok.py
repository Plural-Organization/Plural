from pathlib import Path

from plural.agent.providers.cli.agents.base import INSTRUCTIONS, Call
from plural.agent.providers.cli.agents.claude_stream import ClaudeStreamCli


class GrokCliProvider(ClaudeStreamCli):
    adapter = "grok_cli"
    label = "Grok CLI"
    binary = "grok"
    install = "see x.ai/cli"
    login = "grok login"

    def command(self, prompt: str, run_dir: Path) -> Call:
        # A long conversation would not fit in one argument, so it goes in a file.
        request = run_dir / "request.md"
        request.write_text(prompt, encoding="utf-8")
        return Call(
            [
                *self.model_flag("-m"),
                "--prompt-file",
                str(request),
                "--output-format",
                "streaming-json",
                "--system-prompt-override",
                INSTRUCTIONS,
                "--permission-mode",
                "plan",
                "--no-subagents",
                "--disable-web-search",
            ]
        )
