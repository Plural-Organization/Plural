"""Code mode: the file tools as Python functions behind one `run_code` tool.

An experiment with the code mode of pydantic-ai-harness. Its toolset renders the folded tools
as function signatures, runs the model's code in the Monty sandbox and sends each call the
code makes back here, where it runs as any tool call does: through the hooks, the folder gate
and the approval policy.
"""

import json
from collections.abc import Iterable, Mapping
from contextlib import AsyncExitStack
from typing import Any, cast

from pydantic import Field, JsonValue
from pydantic_ai import RunContext
from pydantic_ai import Tool as PydanticTool
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.messages import ToolReturn
from pydantic_ai.models.test import TestModel
from pydantic_ai.tool_manager import ToolManager
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RunUsage
from pydantic_ai_harness.code_mode import CodeModeToolset

from plural.agent.providers.base import ToolSchema
from plural.agent.tools.base import (
    PreparedCall,
    Tool,
    ToolArgs,
    ToolCtx,
    ToolError,
    ToolResult,
    args_schema,
)
from plural.agent.tools.registry import ToolRegistry
from plural.agent.tools.truncation import truncate_tail
from plural.protocol.models import ToolRisk

RUN_CODE = "run_code"
# The tools the code calls as functions. `bash` stays a tool of its own: a shell command
# quoted inside a Python string is harder to write than either alone.
FOLDED = ("read", "grep", "glob", "ls", "edit", "write")
SUBJECT_CHARS = 80
GUIDELINE = (
    "Do file work in `run_code`: read, search and edit several files in one call, in parallel "
    "with `asyncio.gather`, and return only what you need rather than whole files"
)


class RunCodeArgs(ToolArgs):
    code: str = Field(description="The Python code to execute in the sandbox.")
    restart: bool = Field(
        default=False, description="Set to true to reset REPL state, which is kept otherwise."
    )


class CallFailed(Exception):
    """A folded tool's error, raised in the sandbox where the code called it."""


class CodeMode:
    """Gives the registry its `run_code` tool. `start` before the first model call."""

    def __init__(self, registry: ToolRegistry, folded: Iterable[str] = FOLDED) -> None:
        self._registry = registry
        self._folded = tuple(folded)
        self._stack = AsyncExitStack()
        self._toolset: Any = None
        self._description = ""

    async def start(self) -> None:
        functions = FunctionToolset[ToolCtx]([self._function(name) for name in self._folded])
        toolset = await CodeModeToolset[ToolCtx](wrapped=functions).for_run(self._context(None))
        self._toolset = await self._stack.enter_async_context(toolset)
        described = await self._toolset.get_tools(self._context(None))
        self._description = described[RUN_CODE].tool_def.description or ""

    async def close(self) -> None:
        await self._stack.aclose()

    def tools(self) -> Iterable[Tool]:
        return (self,) if self._toolset is not None else ()

    @property
    def name(self) -> str:
        return RUN_CODE

    @property
    def guidelines(self) -> tuple[str, ...]:
        return (GUIDELINE,)

    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=RUN_CODE, description=self._description, parameters=args_schema(RunCodeArgs)
        )

    def prepare(self, raw: Mapping[str, JsonValue]) -> PreparedCall:
        args = RunCodeArgs.model_validate(raw)
        first = next((line.strip() for line in args.code.splitlines() if line.strip()), "")
        return PreparedCall(
            name=RUN_CODE,
            # Reading is all the code does by itself: each call it makes is checked as its own.
            risk=ToolRisk.READ,
            subject=first[:SUBJECT_CHARS],
            execute=lambda ctx: self._run(args, ctx),
        )

    async def _run(self, args: RunCodeArgs, ctx: ToolCtx) -> ToolResult:
        context = self._context(ctx)
        tools = await self._toolset.get_tools(context)
        try:
            returned = await self._toolset.call_tool(
                RUN_CODE, {"code": args.code, "restart": args.restart}, context, tools[RUN_CODE]
            )
        except ModelRetry as retry:
            return ToolResult(truncate_tail(retry.message, full=ctx.outputs), is_error=True)
        value = returned.return_value if isinstance(returned, ToolReturn) else returned
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return ToolResult(truncate_tail(text, full=ctx.outputs))

    def _context(self, ctx: ToolCtx | None) -> RunContext[ToolCtx]:
        return RunContext(
            deps=cast("ToolCtx", ctx),
            model=TestModel(),
            usage=RunUsage(),
            tool_manager=ToolManager(toolset=self._toolset) if self._toolset is not None else None,
            tool_call_id=RUN_CODE,
            tool_name=RUN_CODE,
        )

    def _function(self, name: str) -> PydanticTool[ToolCtx]:
        tool = self._registry.get(name)
        schema = tool.schema()

        async def call(context: RunContext[ToolCtx], **kwargs: Any) -> str:
            nested = context.deps.call
            if nested is None:
                raise ToolError(f"{name} cannot be called here")
            result = await nested(name, kwargs)
            if result.is_error:
                raise CallFailed(result.content)
            return result.content

        # Every function is async, so the code awaits them all alike; the file tools lock the
        # file they change, which keeps calls the code gathers from colliding.
        return PydanticTool[ToolCtx].from_schema(
            call,
            name=name,
            description=schema.description,
            json_schema=dict(schema.parameters),
            takes_ctx=True,
        )
