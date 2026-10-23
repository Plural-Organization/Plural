import re
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from typing import Final

from pydantic import Field

from plural.agent.tools.base import ToolArgs, ToolCtx, ToolError, ToolResult, ToolSpec, TypedTool
from plural.agent.tools.glob import WALK_LIMIT
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

    async def run(self, args: GrepArgs, ctx: ToolCtx) -> ToolResult:
        try:
            regex = re.compile(args.pattern, re.IGNORECASE if args.ignore_case else 0)
        except re.error as error:
            raise ToolError(f"invalid pattern: {error}") from error
        base = ctx.workspace.resolve(args.path)
        matches: list[str] = []
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
                    matches.append(f"{relative}:{number}: {line[:MAX_LINE_CHARS]}")
                    if len(matches) >= MAX_MATCHES:
                        return ToolResult(truncate_head("\n".join(matches)))
        return ToolResult(truncate_head("\n".join(matches)) or "(no matches)")
