"""CLIs that write Claude Code's stream-json: Qwen Code, Cursor, Kimi, Grok and Amp."""

from typing import cast

from plural.agent.providers.cli.prompt_cli import Event, PromptCliProvider, as_dict, int_of
from plural.protocol.models import Usage


def _usage(data: dict[str, object] | None) -> Usage | None:
    if data is None:
        return None
    return Usage(
        input_tokens=int_of(data, "input_tokens"),
        output_tokens=int_of(data, "output_tokens"),
        cache_read_tokens=int_of(data, "cache_read_input_tokens"),
        cache_write_tokens=int_of(data, "cache_creation_input_tokens"),
    )


class ClaudeStreamCli(PromptCliProvider):
    """A CLI whose output reads like Claude Code's: assistant messages, deltas and a result."""

    def parse(self, event: dict[str, object]) -> Event | None:
        kind = event.get("type")
        if kind == "assistant":
            message = as_dict(event.get("message")) or {}
            content = message.get("content")
            if isinstance(content, str):
                return Event(message=content) if content else None
            blocks = cast("list[object]", content) if isinstance(content, list) else []
            text = "".join(
                str(block.get("text", ""))
                for raw in blocks
                if (block := as_dict(raw)) is not None and block.get("type") == "text"
            )
            return Event(message=text) if text else None
        if kind == "stream_event":
            inner = as_dict(event.get("event")) or {}
            delta = as_dict(inner.get("delta")) or {}
            text = delta.get("text")
            if delta.get("type") == "text_delta" and isinstance(text, str):
                return Event(delta=text)
            return None
        if kind == "result":
            result = event.get("result")
            error = as_dict(event.get("error"))
            failed = event.get("is_error") is True or event.get("subtype") == "error"
            detail = error.get("message") if error is not None else result
            return Event(
                message=result if isinstance(result, str) and result and not failed else None,
                usage=_usage(as_dict(event.get("usage"))),
                error=str(detail or f"{self.label} reported an error") if failed else None,
            )
        if kind == "error":
            return Event(error=str(event.get("message") or event.get("error") or "error"))
        return None
