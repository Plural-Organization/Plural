import io
from typing import Any
from urllib.request import Request

import pytest

from plural import __version__
from plural.host import team


class _Response(io.BytesIO):
    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def test_directory_requests_identify_plural_not_python_urllib(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A relay behind Cloudflare refuses the default "Python-urllib" agent with error 1010.
    seen: list[Request] = []

    def fake_urlopen(request: Request, **_: Any) -> _Response:
        seen.append(request)
        return _Response(b"{}")

    monkeypatch.setattr(team, "urlopen", fake_urlopen)
    team._call(  # pyright: ignore[reportPrivateUsage]
        "POST", "https://relay.example/teams", b"{}", {"content-type": "application/json"}
    )

    assert seen[0].get_header("User-agent") == f"plural/{__version__}"
    assert seen[0].get_header("Content-type") == "application/json"
