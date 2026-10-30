import asyncio
import http.client
import ipaddress
import socket
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Final
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from pydantic import Field

from plural.agent.tools.base import ToolArgs, ToolCtx, ToolError, ToolResult, ToolSpec, TypedTool
from plural.protocol.models import ToolRisk

MAX_DOWNLOAD_BYTES: Final = 1_000_000
MAX_REDIRECTS: Final = 5
USER_AGENT: Final = "Plural-Agent/0.1 (+https://github.com/Plural-Organization/Plural)"
ALLOWED_CONTENT_TYPES: Final = (
    "text/",
    "application/json",
    "application/xml",
    "application/xhtml+xml",
)


@dataclass(frozen=True, slots=True)
class WebResponse:
    url: str
    content_type: str
    body: bytes


class PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, address: str, timeout_s: float) -> None:
        super().__init__(host, port, timeout=timeout_s)
        self._connect_address = address

    def connect(self) -> None:
        self.sock = socket.create_connection((self._connect_address, self.port), self.timeout)


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, address: str, timeout_s: float) -> None:
        context = ssl.create_default_context()
        super().__init__(host, port, timeout=timeout_s, context=context)
        self._connect_address = address
        self._tls_context: ssl.SSLContext = context

    def connect(self) -> None:
        sock = socket.create_connection((self._connect_address, self.port), self.timeout)
        self.sock = self._tls_context.wrap_socket(sock, server_hostname=self.host)


def _resolve(host: str, port: int) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise ToolError(f"could not resolve host: {host}") from error
    return {ipaddress.ip_address(record[4][0]) for record in records}


def validate_public_url(
    url: str,
    *,
    resolver: Callable[[str, int], set[ipaddress.IPv4Address | ipaddress.IPv6Address]] = _resolve,
) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        parsed = urlsplit(url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as error:
        raise ToolError(f"invalid URL: {error}") from error
    if parsed.scheme not in {"http", "https"}:
        raise ToolError("only http and https URLs are allowed")
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise ToolError("URL must contain a public host and no credentials")
    if port not in {80, 443}:
        raise ToolError("only ports 80 and 443 are allowed")
    addresses = resolver(parsed.hostname, port)
    if not addresses or any(not address.is_global for address in addresses):
        raise ToolError("URL resolves to a private, local, or reserved address")
    return addresses


def _read_once(
    url: str,
    timeout_s: float,
    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address],
) -> tuple[int, dict[str, str], bytes]:
    parsed = urlsplit(url)
    host = parsed.hostname
    if host is None:
        raise ToolError("URL must contain a public host and no credentials")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    address = str(min(addresses, key=lambda item: (item.version, int(item))))
    connection: http.client.HTTPConnection
    if parsed.scheme == "https":
        connection = PinnedHTTPSConnection(host, port, address, timeout_s)
    else:
        connection = PinnedHTTPConnection(host, port, address, timeout_s)
    try:
        connection.request(
            "GET",
            path,
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
        )
        response = connection.getresponse()
        body = response.read(MAX_DOWNLOAD_BYTES + 1)
        if len(body) > MAX_DOWNLOAD_BYTES:
            raise ToolError(f"response exceeds {MAX_DOWNLOAD_BYTES} bytes")
        return response.status, dict(response.getheaders()), body
    except (TimeoutError, OSError, http.client.HTTPException) as error:
        raise ToolError(f"request failed: {error}") from error
    finally:
        connection.close()


def ascii_url(url: str) -> str:
    """The URL as it goes on the wire: punycode host, percent-encoded path and query."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    try:
        wire_host = host.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise ToolError(f"{host} is not a valid host name") from error
    netloc = f"[{wire_host}]" if ":" in wire_host else wire_host
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    if parts.username is not None:
        user = quote(parts.username, safe="")
        password = f":{quote(parts.password, safe='')}" if parts.password is not None else ""
        netloc = f"{user}{password}@{netloc}"
    return urlunsplit(
        (
            parts.scheme,
            netloc,
            quote(parts.path, safe="/%:@!$&'()*+,;=-._~"),
            quote(parts.query, safe="/?%:@!$&'()*+,;=-._~"),
            "",
        )
    )


async def fetch_url(url: str, *, timeout_s: float = 15) -> WebResponse:
    current = ascii_url(url)
    for _ in range(MAX_REDIRECTS + 1):
        addresses = await asyncio.to_thread(validate_public_url, current)
        status, headers, body = await asyncio.to_thread(_read_once, current, timeout_s, addresses)
        if 300 <= status < 400:
            location = headers.get("Location") or headers.get("location")
            if not location:
                raise ToolError("redirect response has no Location header")
            current = ascii_url(urljoin(current, location))
            continue
        content_type = (headers.get("Content-Type") or headers.get("content-type") or "").lower()
        media_type = content_type.split(";", 1)[0].strip()
        if not any(media_type.startswith(allowed) for allowed in ALLOWED_CONTENT_TYPES):
            raise ToolError(f"unsupported content type: {media_type or 'missing'}")
        return WebResponse(url=current, content_type=content_type, body=body)
    raise ToolError(f"too many redirects (maximum {MAX_REDIRECTS})")


def _decode(response: WebResponse) -> str:
    charset = "utf-8"
    for part in response.content_type.split(";")[1:]:
        key, _, value = part.strip().partition("=")
        if key.lower() == "charset" and value:
            charset = value.strip("\"'")
    try:
        return response.body.decode(charset, errors="replace")
    except LookupError:
        return response.body.decode("utf-8", errors="replace")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "svg", "noscript"}:
            self._ignored += 1
        elif not self._ignored and tag in {"p", "br", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg", "noscript"} and self._ignored:
            self._ignored -= 1
        elif not self._ignored and tag in {"p", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored:
            self.parts.append(data)

    def text(self) -> str:
        lines = (" ".join(part.split()) for part in "".join(self.parts).splitlines())
        return "\n".join(line for line in lines if line)


def extract_text(raw: str, content_type: str) -> str:
    if "html" not in content_type:
        return raw.strip()
    parser = _TextExtractor()
    parser.feed(raw)
    return parser.text()


class WebFetchArgs(ToolArgs):
    url: str = Field(min_length=1, description="Public HTTP(S) URL to fetch.")
    max_chars: int = Field(default=20_000, ge=1_000, le=50_000)


class WebFetchTool(TypedTool[WebFetchArgs]):
    spec = ToolSpec(
        name="web_fetch",
        description=(
            "Fetch a public HTTP(S) page as text. Private hosts, credentials, unsafe redirects, "
            "non-text content, and oversized responses are blocked."
        ),
        risk=ToolRisk.READ,
        args_model=WebFetchArgs,
    )

    def subject(self, args: WebFetchArgs) -> str:
        return args.url

    async def run(self, args: WebFetchArgs, ctx: ToolCtx) -> ToolResult:
        response = await fetch_url(args.url)
        text = extract_text(_decode(response), response.content_type)
        if len(text) > args.max_chars:
            text = f"{text[: args.max_chars]}\n[truncated at {args.max_chars} characters]"
        return ToolResult(f"Source: {response.url}\n\n{text}")
