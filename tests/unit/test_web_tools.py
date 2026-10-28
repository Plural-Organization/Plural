import ipaddress
from pathlib import Path

import pytest

from plural.agent.sandbox.base import Workspace
from plural.agent.sandbox.local import LocalBackend
from plural.agent.tools import web
from plural.agent.tools.base import ToolCtx, ToolError
from plural.agent.tools.web import (
    SearchResult,
    WebFetchTool,
    WebResponse,
    WebSearchTool,
    extract_text,
    parse_search_results,
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


def test_duckduckgo_results_are_parsed() -> None:
    raw = """
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa">Title</a>
    <a class="result__snippet">A useful snippet.</a>
    """
    assert parse_search_results(raw) == [
        SearchResult(title="Title", url="https://example.com/a", snippet="A useful snippet.")
    ]


def test_bing_results_and_redirects_are_parsed() -> None:
    raw = """
    <li class="b_algo"><h2><a href="https://www.bing.com/ck/a?u=a1aHR0cHM6Ly9leGFtcGxlLmNvbS8">
    A <strong>result</strong></a></h2><div class="b_caption"><p>Useful snippet.</p></div></li>
    """
    assert parse_search_results(raw) == [
        SearchResult(title="A result", url="https://example.com/", snippet="Useful snippet.")
    ]


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


async def test_web_search_limits_and_formats_results(
    ctx: ToolCtx, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = b"""
    <a class="result__a" href="https://one.example">One</a><a class="result__snippet">First</a>
    <a class="result__a" href="https://two.example">Two</a><a class="result__snippet">Second</a>
    """

    async def fake_fetch(url: str, *, timeout_s: float = 15) -> WebResponse:
        assert "plural+agent" in url
        return WebResponse(url=url, content_type="text/html; charset=utf-8", body=body)

    monkeypatch.setattr(web, "fetch_url", fake_fetch)
    prepared = WebSearchTool().prepare({"query": "plural agent", "max_results": 1})
    result = await prepared.execute(ctx)
    assert result.content == "1. One\nhttps://one.example\nFirst"
    assert "Two" not in result.content
