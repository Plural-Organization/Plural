import asyncio
from collections.abc import Callable

from pydantic import Field

from plural.agent.skills import SKILL_FILE, SkillError, SkillLibrary, parse_package
from plural.agent.tools.base import ToolArgs, ToolCtx, ToolError, ToolResult, ToolSpec, TypedTool
from plural.agent.tools.truncation import truncate_head
from plural.protocol.models import SkillScope, ToolRisk

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


class SkillSearchArgs(ToolArgs):
    query: str = Field(min_length=1, max_length=100, description="What the skill should help with.")


class SkillSearchTool(TypedTool[SkillSearchArgs]):
    spec = ToolSpec(
        name="skill_search",
        description=(
            "Search the public skills.sh catalog for installable skills. Prefer well-known "
            "sources with many installs, and suggest one to the host before installing it."
        ),
        risk=ToolRisk.READ,
        args_model=SkillSearchArgs,
    )

    def __init__(self, library: SkillLibrary) -> None:
        self._library = library

    def subject(self, args: SkillSearchArgs) -> str:
        return args.query

    async def run(self, args: SkillSearchArgs, ctx: ToolCtx) -> ToolResult:
        try:
            hits = await self._library.search(args.query)
        except SkillError as error:
            raise ToolError(str(error)) from None
        if not hits:
            return ToolResult(f"no skills found for {args.query!r}")
        return ToolResult("\n".join(f"{hit.package}  ({hit.installs} installs)" for hit in hits))


class SkillInstallArgs(ToolArgs):
    package: str = Field(description="owner/repo@skill, as skill_search lists it.")
    scope: SkillScope = Field(
        default=SkillScope.PROJECT,
        description="project installs into the workspace, global for every session on the host.",
    )


class SkillInstallTool(TypedTool[SkillInstallArgs]):
    spec = ToolSpec(
        name="skill_install",
        description="Install a skill from GitHub. The host approves every install.",
        risk=ToolRisk.WRITE,
        args_model=SkillInstallArgs,
    )

    def __init__(self, library: SkillLibrary, on_change: Callable[[], None]) -> None:
        self._library = library
        self._on_change = on_change

    def subject(self, args: SkillInstallArgs) -> str:
        return args.package if args.scope is SkillScope.PROJECT else f"{args.package} (global)"

    async def run(self, args: SkillInstallArgs, ctx: ToolCtx) -> ToolResult:
        try:
            skill = await self._library.install(parse_package(args.package), args.scope)
        except SkillError as error:
            raise ToolError(str(error)) from None
        self._on_change()
        return ToolResult(
            f"Installed the {skill.name} skill into {skill.path}. Load it with skill."
        )


def skill_tools(
    library: SkillLibrary, on_change: Callable[[], None]
) -> tuple[SkillTool, SkillSearchTool, SkillInstallTool]:
    return SkillTool(library), SkillSearchTool(library), SkillInstallTool(library, on_change)
