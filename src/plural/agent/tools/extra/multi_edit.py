from pydantic import Field

from plural.agent.tools.base import ToolArgs, ToolCtx, ToolResult, ToolSpec, TypedTool
from plural.agent.tools.core.edit import Replacement, apply
from plural.protocol.models import ToolRisk


class MultiEditArgs(ToolArgs):
    path: str = Field(description="File path relative to the workspace root.")
    edits: tuple[Replacement, ...] = Field(
        min_length=1,
        max_length=50,
        description="Replacements applied in order, each to the result of the previous one.",
    )


class MultiEditTool(TypedTool[MultiEditArgs]):
    spec = ToolSpec(
        name="multi_edit",
        description=(
            "Apply several replacements to one file at once. Either all of them apply or "
            "none does. Read the file first."
        ),
        risk=ToolRisk.WRITE,
        args_model=MultiEditArgs,
    )

    def subject(self, args: MultiEditArgs) -> str:
        return args.path

    async def run(self, args: MultiEditArgs, ctx: ToolCtx) -> ToolResult:
        return await apply(ctx, args.path, args.edits)
