import pytest

from plural.host.attachments import image_type


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"\x89PNG\r\n\x1a\n...", "image/png"),
        (b"\xff\xd8\xff\xe0...", "image/jpeg"),
        (b"GIF89a...", "image/gif"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"just some text", None),
        (b"", None),
    ],
)
def test_images_are_recognised_by_their_bytes(data: bytes, expected: str | None) -> None:
    assert image_type(data) == expected
