from pathlib import Path

from plural.agent.providers.cli.agents.base import Call
from plural.agent.providers.cli.agents.claude_stream import ClaudeStreamCli


class AmpCliProvider(ClaudeStreamCli):
    adapter = "amp_cli"
    label = "Amp"
    binary = "amp"
    install = "npm install -g @sourcegraph/amp"
    login = "amp login"

    def command(self, prompt: str, run_dir: Path) -> Call:
        # Execute mode reads the request from stdin; Amp picks its own model.
        return Call(["-x", "--stream-json"], prompt.encode())
