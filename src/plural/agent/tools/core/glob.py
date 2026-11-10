from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from typing import Final

from pydantic import Field

from plural.agent.tools.base import Reach, ToolArgs, ToolCtx, ToolResult, ToolSpec, TypedTool
from plural.agent.tools.truncation import truncate_head
from plural.protocol.models import ToolRisk

WALK_LIMIT: Final = 20_000


def matches_pattern(relative: str, pattern: str) -> bool:
    """A workspace path against a glob. A leading `**/` also matches no folder at all, as in a
    shell: `**/*` or `**/*.py` find the files at the root too. A pattern without a slash matches
    a file's name anywhere."""
    if fnmatchcase(relative, pattern):
        return True
    if pattern.startswith("**/") and matches_pattern(relative, pattern[3:]):
        return True
    return "/" not in pattern and fnmatchcase(PurePosixPath(relative).name, pattern)


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

    def reach(self, args: GlobArgs) -> Reach | None:
        return Reach(args.path, write=False)

    async def run(self, args: GlobArgs, ctx: ToolCtx) -> ToolResult:
        base = ctx.workspace.resolve(args.path)
        files = await ctx.backend.walk(base, limit=WALK_LIMIT)
        matches = [
            relative
            for file in files
            if not ctx.workspace.is_denied(file)
            and (relative := ctx.workspace.relative(file))
            and matches_pattern(relative, args.pattern)
        ]
        shown = truncate_head("\n".join(matches))
        if len(files) >= WALK_LIMIT:
            shown += f"\n[only the first {WALK_LIMIT} files were looked at; give a narrower path]"
        return ToolResult(shown or "(no matches)")
