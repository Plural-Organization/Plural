from pathlib import Path

import pytest

from plural.agent.sandbox.base import PathDenied, PathOutsideWorkspace, Workspace
from plural.agent.sandbox.local import LocalBackend
from plural.agent.tools.base import ToolCtx, ToolError
from plural.agent.tools.registry import builtin_tools


@pytest.fixture
def ctx(tmp_path: Path) -> ToolCtx:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hello')\nvalue = 1\n")
    (tmp_path / ".env").write_text("SECRET=1\n")
    return ToolCtx(workspace=Workspace.at(tmp_path), backend=LocalBackend())


async def run(ctx: ToolCtx, name: str, **args: str | float) -> str:
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
