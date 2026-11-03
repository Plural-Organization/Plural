from collections.abc import Callable

from pydantic import Field

from plural.agent.skills import SkillError, SkillLibrary, parse_package
from plural.agent.tools.base import ToolArgs, ToolCtx, ToolError, ToolResult, ToolSpec, TypedTool
from plural.protocol.models import SkillScope, ToolRisk


class SkillSearchArgs(ToolArgs):
    query: str = Field(min_length=1, max_length=100, description="What the skill should help with.")


class SkillSearchTool(TypedTool[SkillSearchArgs]):
    spec = ToolSpec(
        name="skill_search",
        description=(
            "Search the public skills.sh catalog for installable skills. Prefer a well-known "
            "source with many installs that matches the task closely, say in one line which one "
            "you chose and why, then install it with skill_install and load it. Do not search "
            "for small tasks you can already do well, and never install a skill the room did "
            "not need."
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
) -> tuple[SkillSearchTool, SkillInstallTool]:
    return SkillSearchTool(library), SkillInstallTool(library, on_change)
