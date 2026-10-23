from pydantic import Field

from plural.agent.tools.base import ToolArgs, ToolCtx, ToolError, ToolResult, ToolSpec, TypedTool
from plural.agent.tools.diffs import unified_diff
from plural.protocol.models import ToolRisk


class EditArgs(ToolArgs):
    path: str = Field(description="File path relative to the workspace root.")
    old: str = Field(min_length=1, description="Exact text to replace; must occur exactly once.")
    new: str = Field(description="Replacement text.")


class EditTool(TypedTool[EditArgs]):
    spec = ToolSpec(
        name="edit",
        description="Replace one exact occurrence of text in a file.",
        risk=ToolRisk.WRITE,
        args_model=EditArgs,
    )

    def subject(self, args: EditArgs) -> str:
        return args.path

    async def run(self, args: EditArgs, ctx: ToolCtx) -> ToolResult:
        path = ctx.workspace.resolve(args.path)
        async with ctx.locks(path):
            before = (await ctx.backend.read_file(path)).decode()
            occurrences = before.count(args.old)
            if occurrences != 1:
                raise ToolError(f"old text must match exactly once, found {occurrences}")
            after = before.replace(args.old, args.new, 1)
            await ctx.backend.write_file(path, after.encode())
        diff = unified_diff(ctx.workspace.relative(path), before, after)
        return ToolResult(diff, diff=diff)
