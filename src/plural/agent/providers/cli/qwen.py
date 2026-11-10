from pathlib import Path

from plural.agent.providers.cli.prompt_cli import ASK, INSTRUCTIONS, Call
from plural.agent.providers.cli.stream_json import ClaudeStreamCli


class QwenCliProvider(ClaudeStreamCli):
    adapter = "qwen_cli"
    label = "Qwen Code"
    binary = "qwen"
    install = "npm install -g @qwen-code/qwen-code"
    login = "run qwen once and sign in"

    def command(self, prompt: str, run_dir: Path) -> Call:
        # Its own system prompt is replaced; the request goes on stdin. Plan mode is read-only.
        return Call(
            [
                *self.model_flag("-m"),
                "--output-format",
                "stream-json",
                "--approval-mode",
                "plan",
                "--system-prompt",
                INSTRUCTIONS,
                "-p",
                ASK,
            ],
            prompt.encode(),
        )
