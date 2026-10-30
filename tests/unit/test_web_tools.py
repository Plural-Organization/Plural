import ipaddress
from pathlib import Path

import pytest

from plural.agent.sandbox.base import Workspace
from plural.agent.sandbox.local import LocalBackend
from plural.agent.tools.base import ToolCtx, ToolError
from plural.agent.tools.extra import web
from plural.agent.tools.extra.web import (
    WebFetchTool,
    WebResponse,
    ascii_url,
    extract_text,
    validate_public_url,
)


@pytest.fixture
def ctx(tmp_path: Path) -> ToolCtx:
    return ToolCtx(workspace=Workspace.at(tmp_path), backend=LocalBackend())


def addresses(value: str) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    return {ipaddress.ip_address(value)}


def public_address(_host: str, _port: int) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    return addresses("93.184.216.34")


def private_address(_host: str, _port: int) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    return addresses("127.0.0.1")


def test_url_validation_accepts_only_public_http_hosts() -> None:
    validate_public_url("https://example.com/a", resolver=public_address)
    with pytest.raises(ToolError, match="private"):
        validate_public_url("http://localhost/a", resolver=private_address)
    with pytest.raises(ToolError, match="ports"):
        validate_public_url("https://example.com:8443/a", resolver=public_address)
    with pytest.raises(ToolError, match="invalid URL"):
        validate_public_url("https://example.com:not-a-port/a", resolver=public_address)
    with pytest.raises(ToolError, match="credentials"):
        validate_public_url(
            "https://user:pass@example.com/a",
            resolver=public_address,
        )


def test_http_connection_uses_the_validated_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[str, int], float]] = []

    class FakeSocket:
        def close(self) -> None:
            pass

    def connect(address: tuple[str, int], timeout: float) -> FakeSocket:
        calls.append((address, timeout))
        return FakeSocket()

    monkeypatch.setattr(web.socket, "create_connection", connect)
    resolved = validate_public_url("http://example.com/", resolver=public_address)
    address = str(min(resolved, key=lambda item: (item.version, int(item))))
    connection = web.PinnedHTTPConnection("example.com", 80, address, 2)
    connection.connect()
    connection.close()

    assert calls == [(("93.184.216.34", 80), 2)]


def test_extract_text_removes_active_html() -> None:
    raw = "<h1>Hello</h1><script>steal()</script><p>Useful <b>text</b></p>"
    assert extract_text(raw, "text/html") == "Hello\nUseful text"


async def test_web_fetch_returns_source_and_truncated_text(
    ctx: ToolCtx, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_fetch(url: str, *, timeout_s: float = 15) -> WebResponse:
        return WebResponse(
            url="https://example.com/final", content_type="text/plain", body=b"x" * 2000
        )

    monkeypatch.setattr(web, "fetch_url", fake_fetch)
    prepared = WebFetchTool().prepare({"url": "https://example.com", "max_chars": 1000})
    result = await prepared.execute(ctx)
    assert result.content.startswith("Source: https://example.com/final")
    assert "[truncated at 1000 characters]" in result.content


def test_a_url_with_cyrillic_goes_on_the_wire_percent_encoded() -> None:
    assert ascii_url("https://example.com/search?q=Привет+мир") == (
        "https://example.com/search?q=%D0%9F%D1%80%D0%B8%D0%B2%D0%B5%D1%82+%D0%BC%D0%B8%D1%80"
    )
    assert ascii_url("https://пример.рф/путь?a=1&b=%20") == (
        "https://xn--e1afmkfd.xn--p1ai/%D0%BF%D1%83%D1%82%D1%8C?a=1&b=%20"
    )
    assert ascii_url("https://example.com/a b#frag") == "https://example.com/a%20b"

    assert ascii_url("https://Пример.рф:8443/") == "https://xn--e1afmkfd.xn--p1ai:8443/"
    assert ascii_url("https://пользователь@пример.рф/") == (
        "https://%D0%BF%D0%BE%D0%BB%D1%8C%D0%B7%D0%BE%D0%B2%D0%B0%D1%82%D0%B5%D0%BB%D1%8C"
        "@xn--e1afmkfd.xn--p1ai/"
    )
