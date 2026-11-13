import re
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from typing import Final

from pydantic import Field

from plural.agent.tools.base import (
    Reach,
    ToolArgs,
    ToolCtx,
    ToolError,
    ToolResult,
    ToolSpec,
    TypedTool,
)
from plural.agent.tools.core.glob import WALK_LIMIT
from plural.agent.tools.truncation import truncate_head
from plural.protocol.models import ToolRisk

MAX_MATCHES: Final = 200
MAX_LINE_CHARS: Final = 300
BINARY_PROBE: Final = 8192


class GrepArgs(ToolArgs):
    pattern: str = Field(description="Python regular expression.")
    path: str = Field(default=".", description="File or directory to search.")
    include: str | None = Field(default=None, description="Optional glob filter on file names.")
    ignore_case: bool = False


class GrepTool(TypedTool[GrepArgs]):
    spec = ToolSpec(
        name="grep",
        description="Search file contents by regular expression.",
        risk=ToolRisk.READ,
        args_model=GrepArgs,
    )

    def subject(self, args: GrepArgs) -> str:
        return args.pattern

    def reach(self, args: GrepArgs) -> Reach | None:
        return Reach(args.path, write=False)

    async def run(self, args: GrepArgs, ctx: ToolCtx) -> ToolResult:
        try:
            regex = re.compile(args.pattern, re.IGNORECASE if args.ignore_case else 0)
        except re.error as error:
            raise ToolError(f"invalid pattern: {error}") from error
        base = ctx.workspace.resolve(args.path)
        matches: list[str] = []
        # Every match is counted, the first ones shown: a model shown 200 of 5,000 without a word
        # takes them for all, and answers from the wrong part of a log.
        found = 0
        for file in await ctx.backend.walk(base, limit=WALK_LIMIT):
            if ctx.workspace.is_denied(file):
                continue
            relative = ctx.workspace.relative(file)
            if args.include and not fnmatchcase(PurePosixPath(relative).name, args.include):
                continue
            data = await ctx.backend.read_file(file)
            if b"\0" in data[:BINARY_PROBE]:
                continue
            for number, line in enumerate(data.decode(errors="replace").splitlines(), 1):
                if regex.search(line):
                    found += 1
                    if found <= MAX_MATCHES:
                        matches.append(f"{relative}:{number}: {line[:MAX_LINE_CHARS]}")
        shown = truncate_head("\n".join(matches))
        if found > MAX_MATCHES:
            shown += (
                f"\n[the first {MAX_MATCHES} of {found} matches; narrow the pattern, path or "
                "include, or run a shell command that filters and sorts them]"
            )
        return ToolResult(shown or "(no matches)")
