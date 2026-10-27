from pydantic import Field

from plural.agent.tools.base import ToolArgs, ToolCtx, ToolResult, ToolSpec, TypedTool
from plural.agent.tools.diffs import current_bytes, unified_diff
from plural.protocol.models import ToolRisk


class WriteArgs(ToolArgs):
    path: str = Field(description="File path relative to the workspace root.")
    content: str = Field(description="Full new file content.")


class WriteTool(TypedTool[WriteArgs]):
    spec = ToolSpec(
        name="write",
        description=(
            "Create or overwrite a file in the workspace. Prefer edit for changes to an "
            "existing file."
        ),
        risk=ToolRisk.WRITE,
        args_model=WriteArgs,
    )

    def subject(self, args: WriteArgs) -> str:
        return args.path

    async def run(self, args: WriteArgs, ctx: ToolCtx) -> ToolResult:
        path = ctx.workspace.resolve(args.path)
        data = args.content.encode()
        async with ctx.locks(path):
            existing = await current_bytes(ctx, path)
            ctx.stamps.check(path, existing)
            before = existing.decode() if existing is not None else ""
            await ctx.backend.write_file(path, data)
            ctx.stamps.record(path, data)
        relative = ctx.workspace.relative(path)
        diff = unified_diff(relative, before, args.content)
        return ToolResult(f"Wrote {relative}\n{diff}", diff=diff)
