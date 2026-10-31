"""The agent's prompts, kept as Markdown files so they read and diff as prompts.

Like pi, a prompt is plain text with its parts in XML tags, so the model can tell the parts
apart and text placed inside one cannot pass for another.
"""

from functools import cache
from html import escape
from pathlib import Path
from typing import Final

DIRECTORY: Final = Path(__file__).parent


@cache
def prompt(name: str) -> str:
    return (DIRECTORY / f"{name}.md").read_text(encoding="utf-8").strip()


def tag(name: str, body: str, /, **attributes: str) -> str:
    """`body` inside `<name>`. Its own closing tag is escaped, so the text cannot end it early."""
    attrs = "".join(f' {key}="{escape(value, quote=True)}"' for key, value in attributes.items())
    safe = body.replace(f"</{name}", f"&lt;/{name}")
    return f"<{name}{attrs}>\n{safe}\n</{name}>"
