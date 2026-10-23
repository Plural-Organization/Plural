import difflib
from pathlib import Path

from plural.agent.tools.base import ToolCtx


def unified_diff(path: str, before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


async def current_text(ctx: ToolCtx, path: Path) -> str:
    try:
        return (await ctx.backend.read_file(path)).decode()
    except FileNotFoundError:
        return ""
