import asyncio
from pathlib import Path
from typing import Final

from plural.agent.providers.base import ImageType

IMAGE_SIGNATURES: Final[tuple[tuple[bytes, ImageType], ...]] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def image_type(data: bytes) -> ImageType | None:
    """The media type of a PNG, JPEG, GIF or WebP image, judged by its bytes, not its name."""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return next((kind for magic, kind in IMAGE_SIGNATURES if data.startswith(magic)), None)


class AttachmentVault:
    def __init__(self, root: Path) -> None:
        self._root = root

    async def save(self, attachment_id: str, data: bytes) -> None:
        await asyncio.to_thread(self._write, self._root / attachment_id, data)

    async def read(self, attachment_id: str) -> bytes:
        return await asyncio.to_thread((self._root / attachment_id).read_bytes)

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(data)
