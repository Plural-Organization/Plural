from pathlib import Path

from plural.agent.providers.cli.agents.base import AgentCliProvider, Call, Event, as_dict


class CopilotCliProvider(AgentCliProvider):
    adapter = "copilot_cli"
    label = "GitHub Copilot CLI"
    binary = "copilot"
    install = "npm install -g @github/copilot"
    login = "run copilot once and sign in with GitHub"

    def command(self, prompt: str, run_dir: Path) -> Call:
        # No tools of its own, no built-in MCP servers, no repository instructions.
        return Call(
            [
                *self.model_flag("--model"),
                "-p",
                prompt,
                "--output-format",
                "json",
                "--available-tools",
                "",
                "--disable-builtin-mcps",
                "--no-custom-instructions",
                "-s",
            ]
        )

    def parse(self, event: dict[str, object]) -> Event | None:
        data = as_dict(event.get("data")) or {}
        match event.get("type"):
            case "assistant.message_delta":
                delta = data.get("deltaContent")
                return Event(delta=delta) if isinstance(delta, str) else None
            case "assistant.message":
                content = data.get("content")
                return Event(message=content) if isinstance(content, str) and content else None
            case "session.error" | "error":
                return Event(error=str(data.get("message") or event.get("message") or "error"))
            case "result":
                code = event.get("exitCode")
                return Event(error=f"Copilot exited with {code}") if code not in {0, None} else None
            case _:
                return None
