import asyncio

from pydantic import Field

from plural.agent.skills import SKILL_FILE, SkillError, SkillLibrary
from plural.agent.tools.base import ToolArgs, ToolCtx, ToolError, ToolResult, ToolSpec, TypedTool
from plural.agent.tools.truncation import truncate_head
from plural.protocol.models import ToolRisk

MAX_LISTED_FILES = 50


class SkillArgs(ToolArgs):
    name: str = Field(description="Name of an installed skill.")
    file: str = Field(
        default=SKILL_FILE, description="A file inside the skill folder, SKILL.md by default."
    )


class SkillTool(TypedTool[SkillArgs]):
    spec = ToolSpec(
        name="skill",
        description=(
            "Load an installed skill: its SKILL.md instructions, or another file it refers to."
        ),
        risk=ToolRisk.READ,
        args_model=SkillArgs,
    )

    def __init__(self, library: SkillLibrary) -> None:
        self._library = library

    def subject(self, args: SkillArgs) -> str:
        return args.name if args.file == SKILL_FILE else f"{args.name}/{args.file}"

    async def run(self, args: SkillArgs, ctx: ToolCtx) -> ToolResult:
        try:
            path = self._library.file(args.name, args.file)
            text = await asyncio.to_thread(path.read_text, encoding="utf-8", errors="replace")
        except SkillError as error:
            raise ToolError(str(error)) from None
        except OSError as error:
            raise ToolError(f"cannot read {args.file}: {error.strerror}") from None
        if args.file != SKILL_FILE:
            return ToolResult(truncate_head(text))
        root = path.parent
        others = sorted(
            str(item.relative_to(root))
            for item in root.rglob("*")
            if item.is_file() and item.name != SKILL_FILE
        )
        listing = "\n".join(f"- {name}" for name in others[:MAX_LISTED_FILES])
        more = (
            f"\n- … {len(others) - MAX_LISTED_FILES} more" if len(others) > MAX_LISTED_FILES else ""
        )
        files = (
            f"\n\nOther files in this skill (load them with file=…):\n{listing}{more}"
            if others
            else ""
        )
        return ToolResult(truncate_head(f"{text}{files}"))
