"""Code mode: the agent's tools as Python functions behind one `run_code` tool.

An experiment with the code mode of pydantic-ai-harness. Its toolset runs the model's code in
the Monty sandbox and sends each call the code makes back here, where it runs as any tool call
does: through the hooks, the folder gate and the approval policy.

As in pi, every tool the agent has is a function, but the description lists only the tools the
model would see anyway, within a token budget; the code finds the others with `search_tools`.
"""

import json
import keyword
import re
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
from plural.agent.tools.core.discovery import document, rank
from plural.agent.tools.registry import Entry, Exposure, ToolRegistry
from plural.agent.tools.truncation import truncate_tail
from plural.protocol.models import ToolRisk

RUN_CODE = "run_code"
# The tools the model reaches only through code. `bash` stays a tool of its own as well: a
# shell command is easier to write as itself than quoted inside Python.
FOLDED = ("read", "grep", "glob", "ls", "edit", "write")
# Never functions: the code tool itself, and the search that declares tools to the model.
NOT_CALLABLE = frozenset({RUN_CODE, "tool_search"})
# Estimated tokens the listed signatures may take, as pi's codemode.inlineBudget.
INLINE_BUDGET = 3000
SEARCH_LIMIT = 8
SUBJECT_CHARS = 80
GUIDELINE = (
    "Do file work in `run_code`: read, search and edit several files in one call, in parallel "
    "with `asyncio.gather`, and return only what you need rather than whole files"
)
PROSE = """\
Run Python in a sandbox (Monty, a subset of Python) that calls tools as async functions. Use it \
to read, search and change many files in one call, to run calls side by side with \
`await asyncio.gather(...)`, and to return only what you need.
- Functions take keyword arguments only and return text. A failed or denied call raises where \
it is awaited; each call still needs the usual approval.
- The last expression is the result, and print() output is returned with it. Variables persist \
between calls; `restart: true` resets them.
- Only standard modules import (asyncio, json, re, math, collections, itertools, functools, \
datetime, dataclasses, hashlib, base64, csv, tomllib, pathlib, typing). No packages, and no \
files, network or clock except through the functions.
- `await search_tools(query=...)` finds the other tools (MCP servers, web, sub-agents, plugins) \
and `await describe_tool(name=...)` gives one's arguments."""


class RunCodeArgs(ToolArgs):
    code: str = Field(description="The Python code to execute in the sandbox.")
    restart: bool = Field(
        default=False, description="Set to true to reset REPL state, which is kept otherwise."
    )


class CallFailed(Exception):
    """A tool's error, raised in the sandbox where the code called it."""


def python_name(name: str) -> str:
    """The name a tool has in the sandbox: an identifier, with anything else as `_`."""
    cleaned = re.sub(r"\W", "_", name)
    return f"{cleaned}_" if keyword.iskeyword(cleaned) or cleaned[:1].isdigit() else cleaned


def _type(schema: Any) -> str:
    if not isinstance(schema, dict):
        return "Any"
    node = cast("dict[str, Any]", schema)
    if "anyOf" in node:
        return " | ".join(dict.fromkeys(_type(option) for option in node["anyOf"]))
    if "enum" in node:
        return "str"
    return {
        "string": "str",
        "integer": "int",
        "number": "float",
        "boolean": "bool",
        "array": "list",
        "object": "dict",
        "null": "None",
    }.get(str(node.get("type")), "Any")


def signature(schema: ToolSchema, *, full: bool = False) -> str:
    """A tool as the function the code calls: its arguments and what it does."""
    parameters = cast("dict[str, Any]", schema.parameters)
    required = set(cast("list[str]", parameters.get("required", [])))
    properties = cast("dict[str, Any]", parameters.get("properties", {}))
    arguments = ", ".join(
        f"{name}: {_type(spec)}" + ("" if name in required else " = None")
        for name, spec in properties.items()
    )
    head = f"async def {python_name(schema.name)}(*{', ' if arguments else ''}{arguments}) -> str"
    lines = schema.description.strip().splitlines() or [""]
    text = schema.description.strip() if full else lines[0]
    if full:
        notes = [
            f"{name}: {described}"
            for name, spec in properties.items()
            if (described := cast("dict[str, Any]", spec).get("description"))
        ]
        text = "\n".join([text, *notes])
    return f'{head}\n    """{text}"""'


class CodeMode:
    """Gives the registry its `run_code` tool. `start` before the first model call."""

    def __init__(
        self,
        registry: ToolRegistry,
        folded: Iterable[str] = FOLDED,
        *,
        budget: int = INLINE_BUDGET,
    ) -> None:
        self._registry = registry
        self._folded = tuple(folded)
        self._budget = budget
        self._stack = AsyncExitStack()
        self._functions = FunctionToolset[ToolCtx]()
        self._toolset: Any = None
        # Sandbox name to the tool's own, for the tools synced in from the registry.
        self._names: dict[str, str] = {}

    async def start(self) -> None:
        self._functions.add_function(self._search_tools, name="search_tools")
        self._functions.add_function(self._describe_tool, name="describe_tool")
        self._sync()
        toolset = await CodeModeToolset[ToolCtx](wrapped=self._functions).for_run(
            self._context(None)
        )
        self._toolset = await self._stack.enter_async_context(toolset)

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
            name=RUN_CODE, description=self._description(), parameters=args_schema(RunCodeArgs)
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

    def _callable(self) -> dict[str, Entry]:
        return {
            entry.tool.name: entry
            for entry in self._registry.runnable()
            if entry.tool.name not in NOT_CALLABLE
        }

    def _description(self) -> str:
        """The prose and the functions the model would see anyway, while the budget lasts."""
        entries = self._callable()
        shown = [name for name in self._folded if name in entries] + [
            name
            for name, entry in entries.items()
            if entry.exposure is Exposure.CORE and name not in self._folded
        ]
        listed: list[str] = []
        spent = 0
        for name in shown:
            text = signature(entries[name].tool.schema())
            spent += len(text) // 4
            if spent > self._budget:
                break
            listed.append(text)
        hidden = len(entries) - len(listed)
        more = f"\n# and {hidden} more: search_tools()" if hidden else ""
        return f"{PROSE}\n\nFunctions:\n```python\n" + "\n".join(listed) + f"{more}\n```"

    def _sync(self) -> None:
        """Make the functions match the registry: MCP servers and plugins come and go."""
        wanted = {python_name(name): name for name in self._callable()}
        for gone in set(self._names) - set(wanted):
            self._functions.tools.pop(gone, None)
            del self._names[gone]
        for sandbox, name in wanted.items():
            if sandbox not in self._names:
                self._functions.add_tool(self._function(sandbox, name))
                self._names[sandbox] = name

    async def _run(self, args: RunCodeArgs, ctx: ToolCtx) -> ToolResult:
        self._sync()
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

    def _function(self, sandbox: str, name: str) -> PydanticTool[ToolCtx]:
        schema = self._registry.get(name).schema()

        async def call(context: RunContext[ToolCtx], **kwargs: Any) -> str:
            nested = context.deps.call
            if nested is None:
                raise ToolError(f"{name} cannot be called here")
            result = await nested(name, kwargs)
            if result.is_error:
                raise CallFailed(result.content)
            return result.content

        return PydanticTool[ToolCtx].from_schema(
            call,
            name=sandbox,
            description=schema.description,
            json_schema=dict(schema.parameters),
            takes_ctx=True,
        )

    def _search_tools(self, query: str, limit: int = SEARCH_LIMIT) -> list[dict[str, str]]:
        """Find tools to call by what they do. Returns their names and summaries."""
        entries = self._callable()
        found = rank(query, [(name, document(entry)) for name, entry in entries.items()], limit)
        return [
            {
                "name": python_name(name),
                "summary": (entries[name].tool.schema().description.strip().splitlines() or [""])[
                    0
                ],
            }
            for name in found
        ]

    def _describe_tool(self, name: str) -> str:
        """A tool's signature, description and arguments."""
        entry = self._callable().get(self._names.get(name, name))
        if entry is None:
            raise ToolError(f"no tool {name}; find one with search_tools")
        return signature(entry.tool.schema(), full=True)
