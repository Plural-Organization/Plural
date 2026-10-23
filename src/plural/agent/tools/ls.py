from pydantic import Field

from plural.agent.tools.base import ToolArgs, ToolCtx, ToolResult, ToolSpec, TypedTool
from plural.agent.tools.truncation import truncate_head
from plural.protocol.models import ToolRisk


class LsArgs(ToolArgs):
    path: str = Field(default=".", description="Directory relative to the workspace root.")


class LsTool(TypedTool[LsArgs]):
    spec = ToolSpec(
        name="ls",
        description="List a directory in the workspace.",
        risk=ToolRisk.READ,
        args_model=LsArgs,
    )

    def subject(self, args: LsArgs) -> str:
        return args.path

    async def run(self, args: LsArgs, ctx: ToolCtx) -> ToolResult:
        path = ctx.workspace.resolve(args.path)
        entries = await ctx.backend.list_dir(path)
        lines = [
            f"{entry.name}/" if entry.is_dir else entry.name
            for entry in entries
            if not ctx.workspace.is_denied(path / entry.name)
        ]
        return ToolResult(truncate_head("\n".join(lines)) or "(empty)")
