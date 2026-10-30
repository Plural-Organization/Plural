import asyncio
from pathlib import Path

from tests.loop_support import StubGate, collect, turn

from plural.agent.agents import EXPLORE, AgentLibrary, read_agent
from plural.agent.context import ContextBuilder
from plural.agent.events import ToolEnd, ToolOutput, ToolStart
from plural.agent.gate import GateResult
from plural.agent.loop import AgentLoop
from plural.agent.providers.base import LlmEvent, Stop, ToolCallReady, ToolCallRequest
from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.agent.sandbox.base import Workspace
from plural.agent.sandbox.local import LocalBackend
from plural.agent.tools.base import ToolCtx
from plural.agent.tools.extra.agent import AgentTool
from plural.agent.tools.registry import builtin_tools
from plural.host.system import UlidGenerator
from plural.protocol.models import Provenance, Role, SkillScope, ToolCallView, ToolRisk


class OnlyAgents(StubGate):
    """Lets the delegation through, like the host's default rule, and denies everything else."""

    async def check(
        self, call: ToolCallView, *, subject: str, provenance: Provenance
    ) -> GateResult:
        self.seen.append((subject, provenance))
        return GateResult(allowed=call.name == "agent", reason="stub")


def delegate(agent: str, task: str) -> tuple[LlmEvent, ...]:
    call = ToolCallRequest(id="d1", name="agent", args={"agent": agent, "task": task})
    return ToolCallReady(call=call), Stop(reason="tool_use")


def build(
    tmp_path: Path, main: FakeProvider, fast: FakeProvider | None, gate: StubGate
) -> AgentLoop:
    (tmp_path / "a.txt").write_text("alpha\n")
    (tmp_path / "secrets.md").write_text("nope\n")
    tools = builtin_tools()
    library = AgentLibrary(project=tmp_path, home=tmp_path / "home")
    library.refresh()
    tool = AgentTool(library=library, tools=tools, gate=gate, environment=None, ids=UlidGenerator())
    tools.register(tool)
    loop = AgentLoop(
        provider=main,
        helper=fast,
        tools=tools,
        gate=gate,
        context=ContextBuilder(agents=library),
        tool_ctx=ToolCtx(workspace=Workspace.at(tmp_path), backend=LocalBackend()),
        ids=UlidGenerator(),
    )
    tool.attach(lambda: loop)
    return loop


async def test_explore_runs_on_the_fast_model_and_reports_back(tmp_path: Path) -> None:
    main = FakeProvider([delegate("explore", "where is alpha?"), reply("alpha lives in a.txt")])
    fast = FakeProvider([use_tool("grep", "g1", pattern="alpha"), reply("alpha is at a.txt:1")])
    gate = StubGate()
    events = await collect(build(tmp_path, main, fast, gate), turn("find alpha", guest=True))

    started = next(e for e in events if isinstance(e, ToolStart) and e.call.name == "agent")
    assert started.call.risk is ToolRisk.READ
    assert started.call.subject == "explore: where is alpha?"
    progress = "".join(e.chunk for e in events if isinstance(e, ToolOutput))
    assert "explore on the fast model" in progress
    assert "· grep alpha" in progress
    report = next(e for e in events if isinstance(e, ToolEnd) and e.call_id == "d1").result
    assert not report.is_error
    assert report.content.startswith("alpha is at a.txt:1")
    assert "1 tool calls" in report.content

    child_request = fast.requests[0]
    assert child_request.system.startswith("You are explore")
    assert child_request.messages[0].content.endswith("where is alpha?")
    child_tools = {tool.name for tool in child_request.tools}
    # A sub-agent sees every tool of its spec that exists, deferred or not.
    assert child_tools == {"read", "grep", "glob", "ls", "web_fetch"}
    assert not child_tools & {"agent", "write", "bash"}
    assert "# Sub-agents" in main.requests[0].system

    checked = [(subject, provenance.initiator_role) for subject, provenance in gate.seen]
    assert ("alpha", Role.PARTICIPANT) in checked
    assert gate.runs == 1


async def test_without_a_fast_model_the_main_one_does_the_work(tmp_path: Path) -> None:
    main = FakeProvider(
        [delegate("explore", "list files"), reply("a.txt and secrets.md"), reply("done")]
    )
    events = await collect(build(tmp_path, main, None, StubGate()), turn("list"))
    progress = "".join(e.chunk for e in events if isinstance(e, ToolOutput))
    assert "explore on the main model" in progress
    assert main.requests[1].system.startswith("You are explore")


async def test_a_denied_child_call_comes_back_as_an_error_in_the_report(tmp_path: Path) -> None:
    main = FakeProvider([delegate("explore", "read it"), reply("ok")])
    fast = FakeProvider([use_tool("read", "r1", path="a.txt"), reply("could not read a.txt")])
    events = await collect(build(tmp_path, main, fast, OnlyAgents()), turn("go"))
    progress = "".join(e.chunk for e in events if isinstance(e, ToolOutput))
    assert "✗ Denied: stub" in progress
    assert fast.requests[1].messages[-1].content.startswith("Denied")


async def test_stopping_the_run_stops_the_sub_agent(tmp_path: Path) -> None:
    main = FakeProvider([delegate("explore", "wait")])
    gate = StubGate(block=True)
    fast = FakeProvider([use_tool("read", "r1", path="a.txt")])
    loop = build(tmp_path, main, fast, gate)
    cancel = asyncio.Event()

    async def run() -> list[object]:
        return [event async for event in loop.run(turn("go"), cancel=cancel)]

    task = asyncio.create_task(run())
    await asyncio.sleep(0.2)
    cancel.set()
    events = await asyncio.wait_for(task, 5)
    ends = [e for e in events if isinstance(e, ToolEnd) and e.call_id == "d1"]
    assert len(ends) == 1
    assert ends[0].result.is_error


def test_claude_code_agent_files_are_understood(tmp_path: Path) -> None:
    folder = tmp_path / ".claude" / "agents"
    folder.mkdir(parents=True)
    (folder / "reviewer.md").write_text(
        "---\nname: reviewer\ndescription: Reviews a diff for bugs.\n"
        "tools: Read, Grep, Glob, Bash\nmodel: sonnet\n---\n\nYou review diffs.\n"
    )
    (folder / "broken.md").write_text("---\nname: broken\n---\n")
    spec = read_agent(folder / "reviewer.md", SkillScope.PROJECT)
    assert spec is not None
    assert (spec.role, spec.tools, spec.read_only) == (
        "main",
        ("read", "grep", "glob", "bash"),
        False,
    )
    assert spec.prompt == "You review diffs."

    library = AgentLibrary(project=tmp_path, home=tmp_path / "home")
    names = [agent.name for agent in library.refresh()]
    assert names == ["explore", "reviewer"]
    assert library.get("explore") is EXPLORE
