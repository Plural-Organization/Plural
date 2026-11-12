import subprocess
from pathlib import Path

import pytest

from plural.host.plugin_install import install, plugin_name
from plural.host.plugins import PluginError, PluginHost
from plural.protocol.models import PluginStatus

ENTRY = """
from .words import greeting
import deplib


def setup(plural):
    @plural.command("greet")
    async def greet(ctx):
        await ctx.reply(greeting(ctx.author) + deplib.MARK)
"""


def make_package(folder: Path) -> Path:
    folder.mkdir(parents=True)
    (folder / "plugin.py").write_text(ENTRY)
    (folder / "words.py").write_text("def greeting(name):\n    return f'hello {name}'\n")
    deps = folder / ".deps"
    deps.mkdir()
    (deps / "deplib.py").write_text("MARK = '!'\n")
    return folder


def test_names_come_from_the_source() -> None:
    assert plugin_name("https://github.com/acme/plural-plugin-tickets.git") == "tickets"
    assert plugin_name("~/code/My Tools/") == "my-tools"
    assert plugin_name("./ci.py") == "ci"


def test_a_folder_plugin_imports_its_own_modules_and_packages(tmp_path: Path) -> None:
    directory = tmp_path / "plugins"
    make_package(directory / "greeter")
    plugins = PluginHost(directory, workspace=tmp_path)
    plugins.load()
    [view] = plugins.views()
    assert (view.name, view.status, view.error) == ("greeter", PluginStatus.LOADED, None)
    assert view.commands == ("greet",)

    removed = plugins.remove("greeter")
    assert removed == directory / "greeter"
    assert not removed.exists()


def test_install_copies_a_folder_or_a_file_and_never_replaces(tmp_path: Path) -> None:
    directory = tmp_path / "plugins"
    source = make_package(tmp_path / "src" / "greeter")
    target = install(str(source), directory)
    assert target == directory / "greeter"
    assert (target / "words.py").is_file()
    # Its packages are its own to install, not copied from wherever it came from.
    assert not (target / ".deps").exists()
    with pytest.raises(PluginError, match="already installed"):
        install(str(source), directory)

    single = tmp_path / "ci.py"
    single.write_text("def setup(plural):\n    pass\n")
    assert install(str(single), directory) == directory / "ci.py"
    with pytest.raises(PluginError, match=r"no plugin\.py"):
        install(str(tmp_path / "src"), directory, name="empty")
    # A failed install leaves nothing behind.
    assert sorted(path.name for path in directory.iterdir()) == ["ci.py", "greeter"]


def test_install_clones_a_git_repository(tmp_path: Path) -> None:
    repo = tmp_path / "tickets.git"
    repo.mkdir()
    (repo / "plugin.py").write_text("def setup(plural):\n    pass\n")

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init", "-q")
    git("add", ".")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    target = install(str(repo), tmp_path / "plugins")
    assert target == tmp_path / "plugins" / "tickets"
    assert (target / "plugin.py").is_file()
    assert not (target / ".git").exists()
