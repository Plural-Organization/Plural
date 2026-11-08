from pathlib import Path

from plural.agent.providers.cli.agents.base import (
    AgentCliProvider,
    Call,
    Event,
    as_dict,
    int_of,
)
from plural.protocol.models import Usage


class OpencodeCliProvider(AgentCliProvider):
    adapter = "opencode_cli"
    label = "opencode"
    binary = "opencode"
    install = "npm install -g opencode-ai"
    login = "opencode auth login"

    def command(self, prompt: str, run_dir: Path) -> Call:
        # --pure leaves out external plugins; the model is written provider/model.
        return Call(
            [
                "run",
                "--format",
                "json",
                "--pure",
                "--dir",
                str(run_dir),
                *self.model_flag("-m"),
                prompt,
            ]
        )

    def parse(self, event: dict[str, object]) -> Event | None:
        kind = event.get("type")
        part = as_dict(event.get("part")) or {}
        if kind == "text":
            text = part.get("text")
            return Event(message=text) if isinstance(text, str) and text else None
        if kind == "step_finish":
            tokens = as_dict(part.get("tokens"))
            if tokens is None:
                return None
            cache = as_dict(tokens.get("cache"))
            return Event(
                usage=Usage(
                    input_tokens=int_of(tokens, "input"),
                    output_tokens=int_of(tokens, "output"),
                    cache_read_tokens=int_of(cache, "read"),
                    cache_write_tokens=int_of(cache, "write"),
                )
            )
        if kind == "error":
            error = as_dict(event.get("error")) or {}
            data = as_dict(error.get("data")) or {}
            return Event(error=str(data.get("message") or error.get("name") or "opencode failed"))
        return None
