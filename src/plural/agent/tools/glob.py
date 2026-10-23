from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from typing import Final

from pydantic import Field

from plural.agent.tools.base import ToolArgs, ToolCtx, ToolResult, ToolSpec, TypedTool
from plural.agent.tools.truncation import truncate_head
from plural.protocol.models import ToolRisk

WALK_LIMIT: Final = 20_000


class GlobArgs(ToolArgs):
    pattern: str = Field(description="Glob matched against workspace-relative paths or names.")
    path: str = Field(default=".", description="Directory to search from.")


class GlobTool(TypedTool[GlobArgs]):
    spec = ToolSpec(
        name="glob",
        description="Find files by glob pattern.",
        risk=ToolRisk.READ,
        args_model=GlobArgs,
    )

    def subject(self, args: GlobArgs) -> str:
        return args.pattern

    async def run(self, args: GlobArgs, ctx: ToolCtx) -> ToolResult:
        base = ctx.workspace.resolve(args.path)
        files = await ctx.backend.walk(base, limit=WALK_LIMIT)
        matches = [
            relative
            for file in files
            if not ctx.workspace.is_denied(file)
            and (relative := ctx.workspace.relative(file))
            and (
                fnmatchcase(relative, args.pattern)
                or fnmatchcase(PurePosixPath(relative).name, args.pattern)
            )
        ]
        return ToolResult(truncate_head("\n".join(matches)) or "(no matches)")
