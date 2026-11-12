"""Installs a plugin into the host's plugins folder: from a git repository, a folder or a file.

A folder plugin starts from plugin.py and may hold more modules; the packages its
requirements.txt names are installed into its own .deps folder, apart from the host's.
"""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Final

from plural.host.plugins import NAME, PACKAGE_DEPS, PACKAGE_ENTRY, PluginError

REQUIREMENTS: Final = "requirements.txt"
GIT_URL: Final = re.compile(r"^(https?://|git@|ssh://)|\.git$")
TIMEOUT_S: Final = 600


def plugin_name(source: str) -> str:
    """The name a source installs under: its last path part, as a plugin name."""
    stem = source.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git").removesuffix(".py")
    stem = stem.removeprefix("plural-plugin-").removeprefix("plural-")
    return re.sub(r"[^a-z0-9_-]+", "-", stem.lower()).strip("-")


def install(source: str, directory: Path, *, name: str | None = None) -> Path:
    """Install `source` as plugin `name` and return where it went. Nothing is left behind when
    it fails. A plugin already there is not replaced."""
    name = name or plugin_name(source)
    if not NAME.match(name):
        raise PluginError(f"invalid plugin name {name!r}: pass --name with a-z, 0-9, - and _")
    if (directory / f"{name}.py").exists() or (directory / name).exists():
        raise PluginError(f"a plugin named {name} is already installed; remove it first")
    directory.mkdir(parents=True, exist_ok=True)
    local = Path(source).expanduser()
    if local.is_file():
        if local.suffix != ".py":
            raise PluginError("a plugin file is a .py file")
        target = directory / f"{name}.py"
        shutil.copyfile(local, target)
        return target
    with tempfile.TemporaryDirectory(dir=directory, prefix=".install-") as scratch:
        staged = Path(scratch) / name
        if local.is_dir():
            shutil.copytree(local, staged, ignore=shutil.ignore_patterns(".git", PACKAGE_DEPS))
        elif GIT_URL.search(source):
            _run(["git", "clone", "--depth", "1", source, str(staged)], "git clone")
            shutil.rmtree(staged / ".git", ignore_errors=True)
        else:
            raise PluginError(f"{source} is neither a file, a folder nor a git URL")
        if not (staged / PACKAGE_ENTRY).is_file():
            raise PluginError(f"{source} has no {PACKAGE_ENTRY} at its top")
        if (staged / REQUIREMENTS).is_file():
            install_requirements(staged)
        target = directory / name
        staged.rename(target)
    return target


def install_requirements(folder: Path) -> None:
    """Install the packages folder/requirements.txt names into folder/.deps, with uv."""
    uv = shutil.which("uv")
    if uv is None:
        raise PluginError(
            f"{folder.name} needs packages from {REQUIREMENTS}; install uv to set them up"
        )
    _run(
        [
            uv,
            "pip",
            "install",
            "--quiet",
            "--target",
            str(folder / PACKAGE_DEPS),
            "-r",
            str(folder / REQUIREMENTS),
        ],
        "installing its packages",
    )


def _run(argv: list[str], what: str) -> None:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PluginError(f"{what} failed: {error}") from error
    if done.returncode != 0:
        detail = (done.stderr or done.stdout).strip()[-2000:]
        raise PluginError(f"{what} failed: {detail}")
