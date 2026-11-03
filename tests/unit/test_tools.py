import json
from pathlib import Path

import pytest
from pydantic import JsonValue

from plural.agent.sandbox import local
from plural.agent.sandbox.base import PathDenied, PathOutsideWorkspace, Workspace
from plural.agent.sandbox.local import LocalBackend
from plural.agent.tools.base import ToolArgs, ToolCtx, ToolError, args_schema
from plural.agent.tools.registry import builtin_tools
from plural.agent.tools.truncation import OUTPUTS_KEPT, FullOutputs


@pytest.fixture
def ctx(tmp_path: Path) -> ToolCtx:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hello')\nvalue = 1\n")
    (tmp_path / ".env").write_text("SECRET=1\n")
    return ToolCtx(workspace=Workspace.at(tmp_path), backend=LocalBackend())


async def run(ctx: ToolCtx, name: str, **args: str | float | bool) -> str:
    prepared = builtin_tools().get(name).prepare(args)
    return (await prepared.execute(ctx)).content


async def test_read_and_ls(ctx: ToolCtx) -> None:
    assert "print('hello')" in await run(ctx, "read", path="src/app.py")
    listing = await run(ctx, "ls", path=".")
    assert "src/" in listing
    assert ".env" not in listing


async def test_workspace_boundaries(ctx: ToolCtx) -> None:
    with pytest.raises(PathOutsideWorkspace):
        await run(ctx, "read", path="../outside.txt")
    with pytest.raises(PathDenied):
        await run(ctx, "read", path=".env")


async def test_edit_requires_unique_match(ctx: ToolCtx) -> None:
    diff = await run(ctx, "edit", path="src/app.py", old="value = 1", new="value = 2")
    assert "+value = 2" in diff
    with pytest.raises(ToolError):
        await run(ctx, "edit", path="src/app.py", old="missing", new="x")


async def test_edit_replace_all(ctx: ToolCtx) -> None:
    (ctx.workspace.root / "src" / "names.py").write_text("a = 1\nb = a\nc = a\n")
    with pytest.raises(ToolError, match="matches 3 times"):
        await run(ctx, "edit", path="src/names.py", old="a", new="x")
    await run(ctx, "edit", path="src/names.py", old="a", new="x", replace_all=True)
    assert (ctx.workspace.root / "src" / "names.py").read_text() == "x = 1\nb = x\nc = x\n"


async def test_multi_edit_applies_all_or_nothing(ctx: ToolCtx) -> None:
    target = ctx.workspace.root / "src" / "app.py"
    edits: list[JsonValue] = [
        {"old": "hello", "new": "hi"},
        {"old": "value = 1", "new": "value = 2"},
    ]
    prepared = builtin_tools().get("multi_edit").prepare({"path": "src/app.py", "edits": edits})
    result = await prepared.execute(ctx)
    assert "+value = 2" in result.content
    assert target.read_text() == "print('hi')\nvalue = 2\n"

    broken: list[JsonValue] = [{"old": "hi", "new": "hey"}, {"old": "missing", "new": "x"}]
    prepared = builtin_tools().get("multi_edit").prepare({"path": "src/app.py", "edits": broken})
    with pytest.raises(ToolError, match="edit 2: old text was not found; nothing was changed"):
        await prepared.execute(ctx)
    assert target.read_text() == "print('hi')\nvalue = 2\n"


async def test_a_file_changed_after_reading_is_not_overwritten(ctx: ToolCtx) -> None:
    target = ctx.workspace.root / "src" / "app.py"
    await run(ctx, "read", path="src/app.py")
    target.write_text("print('changed by a teammate')\nvalue = 1\n")
    with pytest.raises(ToolError, match="changed since you last read it"):
        await run(ctx, "edit", path="src/app.py", old="value = 1", new="value = 2")
    with pytest.raises(ToolError, match="changed since you last read it"):
        await run(ctx, "write", path="src/app.py", content="x\n")

    await run(ctx, "read", path="src/app.py")
    await run(ctx, "edit", path="src/app.py", old="value = 1", new="value = 2")
    await run(ctx, "edit", path="src/app.py", old="value = 2", new="value = 3")
    assert target.read_text().endswith("value = 3\n")


async def test_write_grep_glob(ctx: ToolCtx) -> None:
    await run(ctx, "write", path="docs/note.md", content="needle here\n")
    assert "docs/note.md:1" in await run(ctx, "grep", pattern="needle")
    assert "docs/note.md" in await run(ctx, "glob", pattern="*.md")


async def test_bash_has_clean_env(ctx: ToolCtx, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-leak")
    output = await run(ctx, "bash", command='echo "key=${ANTHROPIC_API_KEY:-none}"')
    assert "key=none" in output
    assert "[exit 0]" in output


async def test_bash_timeout(ctx: ToolCtx) -> None:
    assert "timed out" in await run(ctx, "bash", command="sleep 5", timeout_s=0.2)


async def test_bash_timeout_keeps_the_output_so_far(ctx: ToolCtx) -> None:
    output = await run(ctx, "bash", command="echo started; sleep 30", timeout_s=3)
    assert "started" in output
    assert "timed out" in output


async def test_long_bash_output_is_kept_whole_for_read(ctx: ToolCtx) -> None:
    output = await run(ctx, "bash", command="seq 1 5000")
    assert output.startswith("[truncated 3000 lines; the whole output is output:1,")
    assert "\n5000\n" in output
    assert "\n1\n" not in output
    head = await run(ctx, "read", path="output:1", limit=3)
    assert head.split() == ["1", "1", "2", "2", "3", "3"]
    assert "3001  3001" in await run(ctx, "read", path="output:1", offset=3000, limit=1)


async def test_short_bash_output_is_not_kept(ctx: ToolCtx) -> None:
    assert not (await run(ctx, "bash", command="echo hi")).startswith("[truncated")
    with pytest.raises(ToolError, match="no longer kept"):
        await run(ctx, "read", path="output:1")


async def test_bash_reports_when_the_captured_output_is_truncated(
    ctx: ToolCtx, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(local, "MAX_CAPTURE_BYTES", 8)
    output = await run(ctx, "bash", command="printf '0123456789ab'")
    assert output == "[output truncated: 4 bytes omitted]\n456789ab\n[exit 0]"
    with pytest.raises(ToolError, match="no longer kept"):
        await run(ctx, "read", path="output:1")


def test_only_the_latest_outputs_are_kept() -> None:
    outputs = FullOutputs()
    refs = [outputs.keep(str(n)) for n in range(OUTPUTS_KEPT + 1)]
    assert outputs.get(refs[0]) is None
    assert outputs.get(refs[-1]) == str(OUTPUTS_KEPT)


def test_tool_schemas_carry_no_titles() -> None:
    class Note(ToolArgs):
        title: str
        tags: tuple[str, ...] = ()

    schema = args_schema(Note)
    assert "title" not in schema
    assert set(schema["properties"]) == {"title", "tags"}
    assert all("title" not in field for field in schema["properties"].values())
    for tool in builtin_tools().schemas():
        assert '"title": "' not in json.dumps(tool.parameters)
