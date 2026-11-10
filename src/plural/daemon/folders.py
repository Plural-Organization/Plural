import asyncio
import secrets
import shutil
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Protocol

MAX_FOLDERS = 50


class FolderPickerUnavailable(Exception):
    """This computer has no way to show a folder dialog."""


class FolderPicker(Protocol):
    async def pick(self) -> Path | None:
        """Shows the system's folder dialog. None means the person closed it."""
        ...


async def _run(*command: str) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    out, _ = await process.communicate()
    return process.returncode or 0, out.decode().strip()


class SystemFolderPicker:
    PROMPT = "Choose the folder Plural will work in"

    async def pick(self) -> Path | None:
        if sys.platform == "darwin":
            code, out = await _run(
                "osascript",
                "-e",
                f'POSIX path of (choose folder with prompt "{self.PROMPT}")',
            )
        elif sys.platform.startswith("win"):
            script = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
                f"$d.Description = '{self.PROMPT}';"
                "if ($d.ShowDialog() -eq 'OK') { $d.SelectedPath }"
            )
            code, out = await _run("powershell", "-NoProfile", "-Command", script)
        elif shutil.which("zenity"):
            code, out = await _run(
                "zenity", "--file-selection", "--directory", f"--title={self.PROMPT}"
            )
        elif shutil.which("kdialog"):
            code, out = await _run("kdialog", "--getexistingdirectory", str(Path.home()))
        else:
            raise FolderPickerUnavailable("no folder dialog (install zenity or kdialog)")
        if code != 0 or not out:
            return None
        chosen = Path(out)
        return chosen if await asyncio.to_thread(chosen.is_dir) else None


class Folders:
    """The folders a person chose, by opaque id: the browser never names a path."""

    def __init__(self, picker: FolderPicker | None = None) -> None:
        self._picker = picker or SystemFolderPicker()
        self._chosen: OrderedDict[str, Path] = OrderedDict()
        self._asking = asyncio.Lock()

    async def pick(self) -> tuple[str, Path] | None:
        if self._asking.locked():
            raise FolderPickerUnavailable("a folder dialog is already open")
        async with self._asking:
            path = await self._picker.pick()
        if path is None:
            return None
        folder_id = f"f_{secrets.token_urlsafe(9)}"
        self._chosen[folder_id] = path.resolve()
        while len(self._chosen) > MAX_FOLDERS:
            self._chosen.popitem(last=False)
        return folder_id, self._chosen[folder_id]

    def get(self, folder_id: str) -> Path | None:
        return self._chosen.get(folder_id)
