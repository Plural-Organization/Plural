from pydantic import Field

from plural.agent.tools.base import ToolArgs, ToolCtx, ToolError, ToolResult, ToolSpec, TypedTool
from plural.agent.tools.diffs import unified_diff
from plural.protocol.models import ToolRisk


class Replacement(ToolArgs):
    old: str = Field(min_length=1, description="Exact text to replace.")
    new: str = Field(description="Replacement text.")
    replace_all: bool = Field(
        default=False,
        description="Replace every occurrence. Without it the text must occur exactly once.",
    )


class EditArgs(Replacement):
    path: str = Field(description="File path relative to the workspace root.")


class MultiEditArgs(ToolArgs):
    path: str = Field(description="File path relative to the workspace root.")
    edits: tuple[Replacement, ...] = Field(
        min_length=1,
        max_length=50,
        description="Replacements applied in order, each to the result of the previous one.",
    )


def replace(text: str, edit: Replacement) -> str:
    occurrences = text.count(edit.old)
    if occurrences == 0:
        raise ToolError("old text was not found")
    if occurrences > 1 and not edit.replace_all:
        raise ToolError(
            f"old text matches {occurrences} times; add context to make it unique "
            "or set replace_all"
        )
    return text.replace(edit.old, edit.new, -1 if edit.replace_all else 1)


async def apply(ctx: ToolCtx, raw_path: str, edits: tuple[Replacement, ...]) -> ToolResult:
    path = ctx.workspace.resolve(raw_path)
    async with ctx.locks(path):
        data = await ctx.backend.read_file(path)
        ctx.stamps.check(path, data)
        before = data.decode()
        after = before
        for index, edit in enumerate(edits, start=1):
            try:
                after = replace(after, edit)
            except ToolError as error:
                prefix = f"edit {index}: " if len(edits) > 1 else ""
                raise ToolError(f"{prefix}{error}; nothing was changed") from None
        written = after.encode()
        await ctx.backend.write_file(path, written)
        ctx.stamps.record(path, written)
    diff = unified_diff(ctx.workspace.relative(path), before, after)
    return ToolResult(diff, diff=diff)


class EditTool(TypedTool[EditArgs]):
    spec = ToolSpec(
        name="edit",
        description="Replace exact text in a file. Read the file first.",
        risk=ToolRisk.WRITE,
        args_model=EditArgs,
    )

    def subject(self, args: EditArgs) -> str:
        return args.path

    async def run(self, args: EditArgs, ctx: ToolCtx) -> ToolResult:
        return await apply(ctx, args.path, (args,))


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
