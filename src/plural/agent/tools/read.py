from pydantic import Field

from plural.agent.tools.base import ToolArgs, ToolCtx, ToolResult, ToolSpec, TypedTool
from plural.agent.tools.truncation import MAX_LINES, truncate_head
from plural.protocol.models import ToolRisk


class ReadArgs(ToolArgs):
    path: str = Field(description="File path relative to the workspace root.")
    offset: int = Field(default=0, ge=0, description="Zero-based first line.")
    limit: int = Field(default=MAX_LINES, ge=1, le=MAX_LINES, description="Maximum lines.")


class ReadTool(TypedTool[ReadArgs]):
    spec = ToolSpec(
        name="read",
        description="Read a text file from the workspace with line numbers.",
        risk=ToolRisk.READ,
        args_model=ReadArgs,
    )

    def subject(self, args: ReadArgs) -> str:
        return args.path

    async def run(self, args: ReadArgs, ctx: ToolCtx) -> ToolResult:
        path = ctx.workspace.resolve(args.path)
        lines = (await ctx.backend.read_file(path)).decode(errors="replace").splitlines()
        window = lines[args.offset : args.offset + args.limit]
        numbered = "\n".join(f"{args.offset + i + 1:>6}  {line}" for i, line in enumerate(window))
        return ToolResult(truncate_head(numbered) or "(empty file)")
