from pathlib import Path

from plural.agent.providers.cli.agents.base import (
    ASK,
    AgentCliProvider,
    Call,
    Event,
    as_dict,
    int_of,
)
from plural.protocol.models import Usage


class GeminiCliProvider(AgentCliProvider):
    adapter = "gemini_cli"
    label = "Gemini CLI"
    binary = "gemini"
    install = "npm install -g @google/gemini-cli"
    login = "run gemini once and sign in with Google"

    def command(self, prompt: str, run_dir: Path) -> Call:
        # The request goes on stdin; -p adds its line after it. Plan mode is read-only.
        return Call(
            [*self.model_flag("-m"), "-o", "stream-json", "--approval-mode", "plan", "-p", ASK],
            prompt.encode(),
        )

    def parse(self, event: dict[str, object]) -> Event | None:
        kind = event.get("type")
        if kind == "message" and event.get("role") == "assistant":
            content = event.get("content")
            if not isinstance(content, str):
                return None
            return Event(delta=content) if event.get("delta") is True else Event(message=content)
        if kind == "result":
            stats = as_dict(event.get("stats"))
            usage = None
            if stats is not None:
                cached = int_of(stats, "cached", "cached_tokens")
                usage = Usage(
                    input_tokens=max(int_of(stats, "input_tokens", "input") - cached, 0),
                    output_tokens=int_of(stats, "output_tokens", "output"),
                    cache_read_tokens=cached,
                )
            error = as_dict(event.get("error")) or {}
            failed = event.get("status") == "error"
            return Event(
                usage=usage,
                error=str(error.get("message") or "Gemini CLI failed") if failed else None,
            )
        if kind == "error":
            return Event(error=str(event.get("message") or "Gemini CLI failed"))
        return None
