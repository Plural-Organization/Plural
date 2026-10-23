import asyncio
from pathlib import Path


class AttachmentVault:
    def __init__(self, root: Path) -> None:
        self._root = root

    async def save(self, attachment_id: str, data: bytes) -> None:
        await asyncio.to_thread(self._write, self._root / attachment_id, data)

    async def read_text(self, attachment_id: str) -> str:
        data = await asyncio.to_thread((self._root / attachment_id).read_bytes)
        return data.decode(errors="replace")

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(data)
