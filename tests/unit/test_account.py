import io
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest
from typer.testing import CliRunner

from plural.cli.main import app
from plural.host import account
from plural.host.account import (
    AccountError,
    AccountStore,
    claim,
    device_login,
    normalize_code,
    renew,
)
from plural.host.relay_http import ConnectFailed
from plural.security.tokens import TokenVerifier

ACCOUNTS = "https://accounts.example"
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


class _Response(io.BytesIO):
    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def reply(*, lasts: timedelta = timedelta(days=7)) -> bytes:
    now = datetime.now(UTC)
    return json.dumps(
        {
            "certificate": "body.signature",
            "expires_at": (now + lasts).isoformat(),
            "email": "alia@example.com",
        }
    ).encode()


class Service:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.answer: bytes | Exception = reply()
        monkeypatch.setattr(account, "urlopen", self._urlopen)

    def _urlopen(self, request: Request, **_: Any) -> _Response:
        assert isinstance(request.data, bytes)
        self.requests.append((request.full_url, json.loads(request.data)))
        if isinstance(self.answer, Exception):
            raise self.answer
        return _Response(self.answer)


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> Service:
    return Service(monkeypatch)


@pytest.fixture
def store(tmp_path: Path) -> AccountStore:
    return AccountStore(tmp_path)


def error(status: int, code: str, message: str) -> HTTPError:
    body = json.dumps({"error": {"code": code, "message": message}}).encode()
    return HTTPError(ACCOUNTS, status, message, None, io.BytesIO(body))  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize("typed", ["k7qf-29xd", "K7QF 29XD", " K7QF29XD ", "K7QF-29XD"])
def test_a_code_is_read_however_it_is_typed(typed: str) -> None:
    assert normalize_code(typed) == "K7QF29XD"


async def test_linking_signs_the_code_with_the_host_key_and_keeps_the_certificate(
    store: AccountStore, service: Service
) -> None:
    entitlement = await claim(store, "k7qf-29xd", ACCOUNTS)
    url, body = service.requests[0]
    assert url == f"{ACCOUNTS}/machines/claim"
    assert body["code"] == "K7QF29XD"
    key = store.signer().verifier.public_b64()
    assert body["key"] == key
    assert TokenVerifier.from_b64(key).verify_proof(b"plural-claim:K7QF29XD", body["signature"])
    assert entitlement.email == "alia@example.com"
    assert store.load() == entitlement
    assert store.path.stat().st_mode & 0o077 == 0


async def test_a_code_of_the_wrong_length_is_refused_before_any_request(
    store: AccountStore, service: Service
) -> None:
    with pytest.raises(AccountError, match="8 letters"):
        await claim(store, "K7QF", ACCOUNTS)
    assert service.requests == []


async def test_the_service_is_heard_when_it_refuses(store: AccountStore, service: Service) -> None:
    service.answer = error(400, "bad_code", "the code is wrong, used or expired")
    with pytest.raises(AccountError, match="wrong, used or expired"):
        await claim(store, "K7QF-29XD", ACCOUNTS)
    assert store.load() is None


async def test_an_unreachable_service_is_said_plainly(
    store: AccountStore, service: Service
) -> None:
    service.answer = URLError(OSError("refused"))
    with pytest.raises(AccountError, match=r"cannot reach accounts\.example"):
        await claim(store, "K7QF-29XD", ACCOUNTS)
    service.answer = URLError(ConnectFailed("slow"))
    with pytest.raises(AccountError, match="did not answer"):
        await claim(store, "K7QF-29XD", ACCOUNTS)


async def test_an_odd_answer_is_not_stored(store: AccountStore, service: Service) -> None:
    service.answer = b'{"certificate": "x"}'
    with pytest.raises(AccountError, match="unexpected"):
        await claim(store, "K7QF-29XD", ACCOUNTS)
    assert store.load() is None


async def test_a_bad_address_is_refused() -> None:
    with pytest.raises(AccountError, match="not an address"):
        await claim(AccountStore(Path("/nonexistent")), "K7QF-29XD", "accounts.example")


async def test_renewing_signs_the_time_and_replaces_the_certificate(
    store: AccountStore, service: Service
) -> None:
    current = await claim(store, "K7QF-29XD", ACCOUNTS)
    service.answer = reply().replace(b"body.signature", b"fresh.certificate")
    renewed = await renew(store, current)
    _, body = service.requests[-1]
    key = store.signer().verifier.public_b64()
    assert TokenVerifier.from_b64(key).verify_proof(
        f"plural-renew:{key}:{body['ts']}".encode(), body["signature"]
    )
    assert renewed.certificate == "fresh.certificate"
    assert store.load() == renewed


async def test_a_certificate_far_from_its_end_is_used_as_it_is(
    store: AccountStore, service: Service
) -> None:
    await claim(store, "K7QF-29XD", ACCOUNTS)
    assert await store.certificate() == "body.signature"
    assert len(service.requests) == 1


async def test_a_certificate_near_its_end_is_renewed_first(
    store: AccountStore, service: Service
) -> None:
    service.answer = reply(lasts=timedelta(hours=3))
    await claim(store, "K7QF-29XD", ACCOUNTS)
    service.answer = reply().replace(b"body.signature", b"fresh.certificate")
    assert await store.certificate() == "fresh.certificate"


async def test_a_failed_renewal_keeps_the_certificate_in_hand(
    store: AccountStore, service: Service
) -> None:
    service.answer = reply(lasts=timedelta(hours=3))
    await claim(store, "K7QF-29XD", ACCOUNTS)
    service.answer = URLError(OSError("offline"))
    assert await store.certificate() == "body.signature"


async def test_nothing_is_sent_when_the_computer_is_not_linked(store: AccountStore) -> None:
    assert await store.certificate() is None


async def test_a_damaged_file_gives_no_certificate_instead_of_stopping_the_host(
    store: AccountStore,
) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{broken")
    assert await store.certificate() is None
    with pytest.raises(AccountError, match="damaged"):
        store.load()


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PLURAL_DATA_DIR", str(tmp_path))
    return tmp_path


def test_login_links_and_whoami_and_logout_follow(home: Path, service: Service) -> None:
    runner = CliRunner()
    linked = runner.invoke(app, ["login", "--code", "K7QF-29XD", "--accounts", ACCOUNTS])
    assert linked.exit_code == 0, linked.output
    assert "Linked to alia@example.com" in linked.output
    who = runner.invoke(app, ["whoami", "--json"])
    assert json.loads(who.output)["email"] == "alia@example.com"
    assert runner.invoke(app, ["whoami"]).exit_code == 0
    assert runner.invoke(app, ["logout"]).exit_code == 0
    gone = runner.invoke(app, ["whoami", "--json"])
    assert gone.exit_code == 1
    assert json.loads(gone.output) == {"linked": False}


def test_login_that_the_service_refuses_exits_with_its_reason(home: Path, service: Service) -> None:
    service.answer = error(403, "unknown_machine", "this computer is not linked to an account")
    result = CliRunner().invoke(app, ["login", "--code", "K7QF-29XD", "--accounts", ACCOUNTS])
    assert result.exit_code == 1
    assert "not linked to an account" in result.output


class Script:
    """The accounts service for the device flow: what each address answers, in turn."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.replies: dict[str, list[bytes | Exception]] = {}
        self.seen: list[tuple[str, dict[str, Any]]] = []
        self.sleeps: list[float] = []
        monkeypatch.setattr(account, "urlopen", self._urlopen)
        monkeypatch.setattr(account, "pause", self._pause)

    async def _pause(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def _urlopen(self, request: Request, **_: Any) -> _Response:
        assert isinstance(request.data, bytes)
        path = request.full_url.removeprefix(ACCOUNTS)
        self.seen.append((path, json.loads(request.data)))
        answer = self.replies[path].pop(0)
        if isinstance(answer, Exception):
            raise answer
        return _Response(answer)


STARTED = json.dumps(
    {
        "device_code": "device-secret",
        "user_code": "K7QF-29XD",
        "verification_url": "https://plrl.host/app?device=K7QF-29XD",
        "expires_in": 600,
        "interval": 3,
    }
).encode()


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> Script:
    return Script(monkeypatch)


def quiet(url: str, code: str) -> None:
    return None


def browser(opened: list[str]) -> Callable[[str], bool]:
    def open_it(url: str) -> bool:
        opened.append(url)
        return True

    return open_it


def pending() -> HTTPError:
    return error(400, "authorization_pending", "waiting for the sign-in on the web")


async def test_the_device_flow_waits_for_the_browser_and_keeps_the_certificate(
    store: AccountStore, script: Script
) -> None:
    script.replies = {"/device/code": [STARTED], "/device/token": [pending(), pending(), reply()]}
    shown: list[tuple[str, str]] = []
    entitlement = await device_login(
        store, ACCOUNTS, show=lambda url, code: shown.append((url, code))
    )
    assert shown == [("https://plrl.host/app?device=K7QF-29XD", "K7QF-29XD")]
    assert script.sleeps == [3, 3, 3]
    assert store.load() == entitlement
    assert entitlement.email == "alia@example.com"


async def test_the_device_flow_names_the_computer_and_proves_the_key(
    store: AccountStore, script: Script
) -> None:
    script.replies = {"/device/code": [STARTED], "/device/token": [reply()]}
    await device_login(store, ACCOUNTS, show=quiet)
    key = store.signer().verifier.public_b64()
    (_, started), (_, collected) = script.seen
    assert started["key"] == key
    assert started["name"] != ""
    assert collected["device_code"] == "device-secret"
    assert TokenVerifier.from_b64(key).verify_proof(
        b"plural-device:device-secret", collected["signature"]
    )


async def test_asking_too_fast_makes_the_flow_ask_less_often(
    store: AccountStore, script: Script
) -> None:
    slow = error(429, "slow_down", "ask less often")
    script.replies = {"/device/code": [STARTED], "/device/token": [slow, pending(), reply()]}
    await device_login(store, ACCOUNTS, show=quiet)
    assert script.sleeps == [3, 5, 5]


async def test_a_refusal_in_the_browser_ends_the_flow(store: AccountStore, script: Script) -> None:
    refused = error(403, "access_denied", "the sign-in was refused on the web")
    script.replies = {"/device/code": [STARTED], "/device/token": [pending(), refused]}
    with pytest.raises(AccountError, match="refused on the web"):
        await device_login(store, ACCOUNTS, show=quiet)
    assert store.load() is None


async def test_nobody_approving_ends_the_flow_after_the_time_given(
    store: AccountStore, script: Script
) -> None:
    script.replies = {"/device/code": [STARTED], "/device/token": [pending() for _ in range(200)]}
    with pytest.raises(AccountError, match="in time"):
        await device_login(store, ACCOUNTS, show=quiet)
    assert sum(script.sleeps) >= 600
    assert store.load() is None


async def test_an_odd_start_is_not_followed(store: AccountStore, script: Script) -> None:
    script.replies = {"/device/code": [b'{"user_code": "K7QF-29XD"}']}
    with pytest.raises(AccountError, match="unexpected"):
        await device_login(store, ACCOUNTS, show=quiet)


def test_login_with_no_code_opens_the_browser_and_links(
    home: Path, script: Script, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr("plural.cli.account.webbrowser.open", browser(opened))
    script.replies = {"/device/code": [STARTED], "/device/token": [pending(), reply()]}
    result = CliRunner().invoke(app, ["login", "--accounts", ACCOUNTS])
    assert result.exit_code == 0, result.output
    assert opened == ["https://plrl.host/app?device=K7QF-29XD"]
    assert "K7QF-29XD" in result.output
    assert "Linked to alia@example.com" in result.output


def test_login_with_no_browser_prints_the_address_only(
    home: Path, script: Script, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr("plural.cli.account.webbrowser.open", browser(opened))
    script.replies = {"/device/code": [STARTED], "/device/token": [reply()]}
    result = CliRunner().invoke(app, ["login", "--accounts", ACCOUNTS, "--no-browser"])
    assert result.exit_code == 0, result.output
    assert opened == []
    assert "https://plrl.host/app?device=K7QF-29XD" in result.output


def test_login_that_nobody_approved_exits_with_the_reason(
    home: Path, script: Script, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("plural.cli.account.webbrowser.open", browser([]))
    refused = error(403, "access_denied", "the sign-in was refused on the web")
    script.replies = {"/device/code": [STARTED], "/device/token": [refused]}
    result = CliRunner().invoke(app, ["login", "--accounts", ACCOUNTS])
    assert result.exit_code == 1
    assert "refused on the web" in result.output
