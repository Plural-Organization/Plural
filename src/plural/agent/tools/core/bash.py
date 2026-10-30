import os
from typing import Final

from pydantic import Field

from plural.agent.tools.base import ToolArgs, ToolCtx, ToolResult, ToolSpec, TypedTool
from plural.agent.tools.streaming import LineStream
from plural.agent.tools.truncation import truncate_tail
from plural.protocol.models import ToolRisk

SAFE_ENV_KEYS: Final = ("PATH", "HOME", "LANG", "LC_ALL", "TERM", "USER", "SHELL", "TMPDIR")


def sandbox_env() -> dict[str, str]:
    return {key: value for key in SAFE_ENV_KEYS if (value := os.environ.get(key)) is not None}


class BashArgs(ToolArgs):
    command: str = Field(min_length=1, description="Shell command run in the workspace root.")
    timeout_s: float = Field(default=120, gt=0, le=600, description="Timeout in seconds.")


class BashTool(TypedTool[BashArgs]):
    spec = ToolSpec(
        name="bash",
        description="Run a shell command in the workspace. Output is tail-truncated.",
        risk=ToolRisk.EXEC,
        args_model=BashArgs,
    )

    def subject(self, args: BashArgs) -> str:
        return args.command

    async def run(self, args: BashArgs, ctx: ToolCtx) -> ToolResult:
        stream = LineStream(ctx.emit)
        try:
            result = await ctx.backend.run(
                args.command,
                cwd=ctx.workspace.root,
                env=sandbox_env(),
                timeout=args.timeout_s,
                on_output=stream.feed,
            )
        finally:
            stream.flush()
        body = truncate_tail(result.output)
        if result.timed_out:
            notice = f"[timed out after {args.timeout_s:g}s]"
            return ToolResult(f"{body}\n{notice}" if body else notice, is_error=True)
        return ToolResult(f"{body}\n[exit {result.exit_code}]", is_error=result.exit_code != 0)
