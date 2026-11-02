import asyncio
from pathlib import Path

import pytest

from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.client.connection import CommandRejected
from plural.protocol.commands import (
    ApprovalRespond,
    CommandRun,
    PermissionModeSet,
    PluginAnswer,
    PluginsCreate,
    PluginsReload,
    PluginsRemove,
    PromptSubmit,
)
from plural.protocol.envelope import ErrorCode
from plural.protocol.events import (
    ApprovalRequested,
    CommandInvoked,
    CommandReplied,
    PluginAsked,
    PluginContextAdded,
    PluginLineSet,
    PluginNotified,
    PluginsChanged,
    PluginShown,
    PromptAccepted,
    RunEnded,
    ToolEnded,
    ToolsLoaded,
)
from plural.protocol.models import ApprovalDecision, PermissionMode, PluginStatus, Role
from tests.e2e.support import running_session

PLUGIN = """
def setup(plural):
    @plural.command("hello", description="Say hello")
    async def hello(ctx):
        await ctx.reply(f"hi {ctx.author}: {ctx.args}")

    @plural.command("ask", description="Ask the agent")
    async def ask(ctx):
        await ctx.prompt(f"please {ctx.args}")

    @plural.command("btw")
    async def btw(ctx):
        await ctx.prompt(f"Answer briefly, prefix BTW: {ctx.args}", display=ctx.args)

    @plural.command("deploy", host_only=True)
    async def deploy(ctx):
        await ctx.reply("deployed")

    @plural.command("broken")
    async def broken(ctx):
        raise ValueError("nope")
"""


def install(tmp_path: Path, name: str, source: str) -> None:
    directory = tmp_path / "data" / "plugins"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.py").write_text(source)


async def test_everyone_sees_plugin_commands_and_their_replies(tmp_path: Path) -> None:
    install(tmp_path, "team", PLUGIN)
    async with running_session(tmp_path, relayed=False, provider=FakeProvider()) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        names = [command.name for command in guest.client.projection.state.commands]
        assert names == ["hello", "ask", "btw", "deploy", "broken"]

        await guest.client.send(CommandRun(name="hello", args="there"))
        invoked = await owner.next(CommandInvoked)
        assert (invoked.command, invoked.args) == ("hello", "there")
        replied = await owner.next(CommandReplied)
        assert (replied.text, replied.ok) == ("hi Alia: there", True)

        with pytest.raises(CommandRejected) as rejected:
            await guest.client.send(CommandRun(name="deploy"))
        assert rejected.value.error.code is ErrorCode.FORBIDDEN
        await owner.client.send(CommandRun(name="deploy"))
        assert (await owner.next(CommandReplied)).text == "deployed"

        await guest.client.send(CommandRun(name="broken"))
        failed = await owner.next(CommandReplied)
        assert not failed.ok
        assert failed.text == "/broken failed: ValueError: nope"

        with pytest.raises(CommandRejected) as missing:
            await guest.client.send(CommandRun(name="nothing"))
        assert missing.value.error.code is ErrorCode.NOT_FOUND


async def test_a_plugin_prompt_belongs_to_whoever_ran_the_command(tmp_path: Path) -> None:
    install(tmp_path, "team", PLUGIN)
    provider = FakeProvider([reply("done")])
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        await guest.client.send(CommandRun(name="ask", args="check the tests"))
        accepted = await owner.next(PromptAccepted)
        assert accepted.text == "please check the tests"
        assert accepted.author_id == guest.client.projection.me_id
        assert accepted.provenance.initiator_role is Role.PARTICIPANT
        assert (accepted.via, accepted.display) == ("ask", None)
        await owner.next(RunEnded)


async def test_the_room_sees_a_plugin_prompts_display_and_the_agent_the_full_text(
    tmp_path: Path,
) -> None:
    install(tmp_path, "team", PLUGIN)
    provider = FakeProvider([reply("BTW: it is fine")])
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        await guest.client.send(CommandRun(name="btw", args="is it fine?"))
        accepted = await guest.next(PromptAccepted)
        assert accepted.text == "Answer briefly, prefix BTW: is it fine?"
        assert (accepted.via, accepted.display) == ("btw", "is it fine?")
        await owner.next(RunEnded)
        assert "Answer briefly, prefix BTW: is it fine?" in str(provider.requests[-1].messages)
        transcript = guest.client.projection.state.transcript
        [entry] = [e for e in transcript if e.id == accepted.prompt_id]
        assert (entry.via, entry.display) == ("btw", "is it fine?")


async def test_viewers_cannot_run_commands(tmp_path: Path) -> None:
    install(tmp_path, "team", PLUGIN)
    async with running_session(tmp_path, relayed=False, provider=FakeProvider()) as session:
        viewer = await session.guest("Vic", role=Role.VIEWER)
        with pytest.raises(CommandRejected) as rejected:
            await viewer.client.send(CommandRun(name="hello"))
        assert rejected.value.error.code is ErrorCode.FORBIDDEN


async def test_the_host_creates_and_reloads_plugins(tmp_path: Path) -> None:
    async with running_session(tmp_path, relayed=False, provider=FakeProvider()) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        with pytest.raises(CommandRejected) as rejected:
            await guest.client.send(PluginsCreate(name="notes"))
        assert rejected.value.error.code is ErrorCode.FORBIDDEN

        await owner.client.send(PluginsCreate(name="notes"))
        await owner.next(PluginsChanged)
        changed = await guest.next(PluginsChanged)
        assert [(view.name, view.status) for view in changed.plugins] == [
            ("notes", PluginStatus.LOADED)
        ]
        await guest.client.send(CommandRun(name="notes", args="x"))
        assert (await guest.next(CommandReplied)).text == "Hello Alia! You wrote: x"

        with pytest.raises(CommandRejected) as again:
            await owner.client.send(PluginsCreate(name="notes"))
        assert again.value.error.code is ErrorCode.CONFLICT

        install(tmp_path, "notes", "def setup(plural):\n    raise RuntimeError('oops')\n")
        await owner.client.send(PluginsReload())
        reloaded = await owner.next(PluginsChanged)
        assert reloaded.plugins[0].error == "RuntimeError: oops"
        assert reloaded.commands == ()

        await owner.client.send(PluginsRemove(name="notes"))
        removed = await owner.next(PluginsChanged)
        assert removed.plugins == ()
        with pytest.raises(CommandRejected) as missing:
            await owner.client.send(PluginsRemove(name="notes"))
        assert missing.value.error.code is ErrorCode.NOT_FOUND


ASIDE = """
def setup(plural):
    @plural.command("aside")
    async def aside(ctx):
        answer = await ctx.ask(ctx.args)
        await ctx.show("btw", answer)
"""


async def test_a_plugin_asks_the_model_aside_and_shows_only_its_author(tmp_path: Path) -> None:
    install(tmp_path, "aside", ASIDE)
    provider = FakeProvider([reply("first answer"), reply("Overfitting is memorising noise.")])
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        await owner.client.send(PromptSubmit(text="look at the model"))
        await owner.next(RunEnded)
        transcript = len(owner.client.projection.state.transcript)

        await guest.client.send(CommandRun(name="aside", args="what is overfitting?"))
        shown = await guest.next(PluginShown)
        assert (shown.command, shown.title) == ("aside", "btw")
        assert shown.text == "Overfitting is memorising noise."
        asked = str(provider.requests[-1].messages)
        assert "look at the model" in asked
        assert "what is overfitting?" in asked

        await owner.client.send(CommandRun(name="aside", args="again?"))
        await owner.next(PluginShown)
        await asyncio.sleep(0.2)
        assert sum(isinstance(event, PluginShown) for event in guest.events) == 1
        assert len(owner.client.projection.state.transcript) == transcript
        assert owner.client.projection.state.run is None


TOOL = """
def setup(plural):
    @plural.tool("ticket", description="Look up a ticket by key", parameters={"key": "Key"})
    async def ticket(args, ctx):
        return f"{args['key']} is open"
"""


async def test_the_agent_calls_a_plugin_tool_after_the_host_approves(tmp_path: Path) -> None:
    install(tmp_path, "tickets", TOOL)
    provider = FakeProvider(
        [
            use_tool("tool_search", query="look up ticket"),
            use_tool("ticket", key="PLR-7"),
            reply("done"),
        ]
    )
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        assert owner.client.projection.state.plugins[0].tools == ("ticket",)
        await owner.client.send(PromptSubmit(text="what about PLR-7?"))
        loaded = await owner.next(ToolsLoaded)
        assert "ticket" in loaded.tools
        approval = await owner.next(ApprovalRequested)
        assert approval.approval.call.name == "ticket"
        await owner.client.send(
            ApprovalRespond(approval_id=approval.approval.id, decision=ApprovalDecision.ONCE)
        )
        ended = await owner.next(ToolEnded)
        assert (ended.ok, ended.output) == (True, "PLR-7 is open")
        await owner.next(RunEnded)
        assert "ticket" not in [tool.name for tool in provider.requests[0].tools]
        assert "ticket" in [tool.name for tool in provider.requests[1].tools]


GUARD = """
def setup(plural):
    @plural.on("tool_call")
    async def guard(call, ctx):
        command = call.args.get("command", "")
        if call.name == "bash" and "git push" in command and "main" in command:
            await ctx.reply("stopped a push to main")
            return plural.deny("pushes to main go through review")
        if call.name == "read" and call.subject.endswith("notes.txt"):
            return plural.ask("it may hold real values")
        if call.name == "ls":
            raise RuntimeError("guard bug")
"""


async def test_a_tool_call_hook_refuses_a_call_even_in_auto_mode(tmp_path: Path) -> None:
    install(tmp_path, "guard", GUARD)
    provider = FakeProvider([use_tool("bash", command="git push origin main"), reply("ok")])
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        await owner.client.send(PermissionModeSet(mode=PermissionMode.AUTO))
        await owner.client.send(PromptSubmit(text="ship it"))
        ended = await owner.next(ToolEnded)
        assert not ended.ok
        assert "refused by the guard plugin: pushes to main go through review" in ended.output
        await owner.next(RunEnded)
        replies = [e.text for e in owner.events if isinstance(e, CommandReplied)]
        assert replies == ["stopped a push to main"]
        assert not any(isinstance(event, ApprovalRequested) for event in owner.events)


async def test_a_tool_call_hook_turns_an_allowed_call_into_an_approval(tmp_path: Path) -> None:
    install(tmp_path, "guard", GUARD)
    provider = FakeProvider(
        [use_tool("read", path="notes.txt"), use_tool("ls", call_id="c2"), reply("ok")]
    )
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        await owner.client.send(PermissionModeSet(mode=PermissionMode.AUTO))
        await owner.client.send(PromptSubmit(text="look around"))
        first = await owner.next(ApprovalRequested)
        assert first.approval.call.name == "read"
        assert first.approval.warnings == ("guard plugin: it may hold real values",)
        await owner.client.send(
            ApprovalRespond(approval_id=first.approval.id, decision=ApprovalDecision.ONCE)
        )
        second = await owner.next(ApprovalRequested)
        assert second.approval.call.name == "ls"
        failed = "guard plugin: its guard failed: RuntimeError: guard bug"
        assert second.approval.warnings == (failed,)
        await owner.client.send(
            ApprovalRespond(approval_id=second.approval.id, decision=ApprovalDecision.ONCE)
        )
        await owner.next(RunEnded)


AFTER = """
def setup(plural):
    @plural.on("run_end")
    async def after(run, ctx):
        await ctx.reply(f"{run.reason} {run.role} {','.join(run.files) or 'nothing'}")
        if run.files:
            await ctx.prompt("run the tests", display="checking the tests")
"""


async def test_a_run_end_hook_reports_the_run_and_can_start_one_more(tmp_path: Path) -> None:
    install(tmp_path, "after", AFTER)
    provider = FakeProvider(
        [use_tool("write", path="hello.txt", content="hi\n"), reply("written"), reply("tests ok")]
    )
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        await owner.client.send(PermissionModeSet(mode=PermissionMode.AUTO))
        await owner.client.send(PromptSubmit(text="write hello"))
        await owner.next(RunEnded)
        assert (await owner.next(CommandReplied)).text == "stop host hello.txt"
        follow = await owner.next(PromptAccepted)
        assert (follow.text, follow.display, follow.via) == (
            "run the tests",
            "checking the tests",
            "after",
        )
        await owner.next(RunEnded)
        await asyncio.sleep(0.2)
        replies = [e.text for e in owner.events if isinstance(e, CommandReplied)]
        assert replies == ["stop host hello.txt"]


STATUS = """
def setup(plural):
    @plural.command("progress")
    async def progress(ctx):
        for step in ("1/3", "2/3", "3/3"):
            plural.status(f"tests {step}")
"""


async def test_a_plugin_status_line_is_shared_throttled_and_dropped_with_the_plugin(
    tmp_path: Path,
) -> None:
    install(tmp_path, "ci", STATUS)
    async with running_session(tmp_path, relayed=False, provider=FakeProvider()) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        await owner.client.send(CommandRun(name="progress"))
        first = await guest.next(PluginLineSet)
        assert (first.plugin, first.text) == ("ci", "tests 1/3")
        last = await guest.next(PluginLineSet, timeout=3)
        assert last.text == "tests 3/3"
        assert [
            (line.plugin, line.text) for line in guest.client.projection.state.plugin_lines
        ] == [("ci", "tests 3/3")]
        await owner.client.send(PluginsRemove(name="ci"))
        await guest.next(PluginsChanged)
        assert guest.client.projection.state.plugin_lines == ()


BEFORE = """
def setup(plural):
    @plural.on("before_run")
    async def branch(prompt, ctx):
        return f"branch feat/x, asked by {prompt.role}"
"""


async def test_a_before_run_hook_gives_the_agent_context_without_tainting_the_run(
    tmp_path: Path,
) -> None:
    install(tmp_path, "git", BEFORE)
    provider = FakeProvider([use_tool("write", path="a.txt", content="a\n"), reply("done")])
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        await owner.client.send(PermissionModeSet(mode=PermissionMode.AUTO))
        await owner.client.send(PromptSubmit(text="write a"))
        added = await owner.next(PluginContextAdded)
        assert (added.plugin, added.text) == ("git", "branch feat/x, asked by host")
        assert (await owner.next(ToolEnded)).ok
        await owner.next(RunEnded)
        assert not any(isinstance(event, ApprovalRequested) for event in owner.events)
        contents = [message.content for message in provider.requests[0].messages]
        context = next(i for i, text in enumerate(contents) if "branch feat/x" in text)
        assert "git plugin" in contents[context]
        assert "write a" in contents[context + 1]


async def test_a_before_run_note_that_has_not_changed_is_not_added_again(tmp_path: Path) -> None:
    install(tmp_path, "git", BEFORE)
    provider = FakeProvider([reply("one"), reply("two")])
    async with running_session(tmp_path, relayed=False, provider=provider) as session:
        owner = await session.owner()
        for text in ("first", "second"):
            await owner.client.send(PromptSubmit(text=text))
            await owner.next(RunEnded)
        added = [event for event in owner.events if isinstance(event, PluginContextAdded)]
        assert len(added) == 1
        second = [message.content for message in provider.requests[1].messages]
        assert sum("branch feat/x" in text for text in second) == 1


STARTUP = """
def setup(plural):
    @plural.on("session_start")
    async def ready(session, ctx):
        plural.status(f"ready in {session.workspace.name}")
        await ctx.reply(f"started in {session.room[:2]}")
"""


async def test_session_start_hooks_run_at_start_and_on_reload(tmp_path: Path) -> None:
    install(tmp_path, "boot", STARTUP)
    async with running_session(tmp_path, relayed=False, provider=FakeProvider()) as session:
        owner = await session.owner()
        await asyncio.sleep(0.2)
        lines = owner.client.projection.state.plugin_lines
        assert [(line.plugin, line.text) for line in lines] == [("boot", "ready in ws")]
        before = [e for e in owner.events if isinstance(e, CommandReplied)]
        await owner.client.send(PluginsReload())
        await owner.next(PluginsChanged)
        await asyncio.sleep(0.2)
        after = [e for e in owner.events if isinstance(e, CommandReplied)]
        assert [(e.command, e.text) for e in after[len(before) :]] == [("boot", "started in r_")]


DEPLOY = """
def setup(plural):
    @plural.command("deploy")
    async def deploy(ctx):
        target = await ctx.select("where to?", ["staging", "prod"])
        if target is None:
            await ctx.reply("cancelled")
            return
        tag = await ctx.input("tag", default="v1")
        if not await ctx.confirm(f"deploy {tag} to {target}?"):
            await ctx.reply("not confirmed")
            return
        await ctx.notify("deploying")
        await ctx.reply(f"deployed {tag} to {target}")
"""


async def test_a_plugin_asks_whoever_ran_it_and_waits_for_the_answers(tmp_path: Path) -> None:
    install(tmp_path, "ops", DEPLOY)
    async with running_session(tmp_path, relayed=False, provider=FakeProvider()) as session:
        owner = await session.owner()
        guest = await session.guest("Alia")
        await guest.client.send(CommandRun(name="deploy"))
        where = await guest.next(PluginAsked)
        assert (where.kind, where.title, where.options) == (
            "select",
            "where to?",
            ("staging", "prod"),
        )
        with pytest.raises(CommandRejected) as stranger:
            await owner.client.send(PluginAnswer(ask_id=where.ask_id, value="prod"))
        assert stranger.value.error.code is ErrorCode.NOT_FOUND
        with pytest.raises(CommandRejected) as wrong:
            await guest.client.send(PluginAnswer(ask_id=where.ask_id, value="moon"))
        assert wrong.value.error.code is ErrorCode.INVALID
        await guest.client.send(PluginAnswer(ask_id=where.ask_id, value="staging"))
        tag = await guest.next(PluginAsked)
        assert (tag.kind, tag.default) == ("input", "v1")
        await guest.client.send(PluginAnswer(ask_id=tag.ask_id, value="v2"))
        sure = await guest.next(PluginAsked)
        assert (sure.kind, sure.options) == ("confirm", ("yes", "no"))
        await guest.client.send(PluginAnswer(ask_id=sure.ask_id, value="yes"))
        assert (await guest.next(PluginNotified)).text == "deploying"
        assert (await owner.next(CommandReplied)).text == "deployed v2 to staging"
        assert not any(isinstance(event, PluginAsked | PluginNotified) for event in owner.events)

        await guest.client.send(CommandRun(name="deploy"))
        closed = await guest.next(PluginAsked)
        await guest.client.send(PluginAnswer(ask_id=closed.ask_id))
        assert (await owner.next(CommandReplied)).text == "cancelled"
