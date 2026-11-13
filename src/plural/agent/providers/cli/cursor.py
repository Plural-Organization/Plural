from pathlib import Path

from plural.agent.providers.cli.prompt_cli import Call
from plural.agent.providers.cli.stream_json import ClaudeStreamCli


class CursorCliProvider(ClaudeStreamCli):
    adapter = "cursor_cli"
    label = "Cursor CLI"
    binary = "cursor-agent"
    install = "curl https://cursor.com/install -fsS | bash"
    login = "cursor-agent login"

    def command(self, prompt: str, run_dir: Path) -> Call:
        # Without --force it runs no commands of its own.
        return Call([*self.model_flag("--model"), "-p", prompt, "--output-format", "stream-json"])
