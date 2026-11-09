import io
import json
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
    Entitlement,
    claim,
    normalize_code,
    plan_line,
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


def reply(*, ends: timedelta = timedelta(days=14), lasts: timedelta = timedelta(days=7)) -> bytes:
    now = datetime.now(UTC)
    return json.dumps(
        {
            "certificate": "body.signature",
            "plan": "trial",
            "expires_at": (now + lasts).isoformat(),
            "plan_ends_at": (now + ends).isoformat(),
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


def entitlement(**changes: Any) -> Entitlement:
    base: dict[str, Any] = {
        "accounts": ACCOUNTS,
        "email": "alia@example.com",
        "certificate": "c",
        "plan": "trial",
        "expires_at": NOW + timedelta(days=7),
        "plan_ends_at": NOW + timedelta(days=13, hours=4),
    }
    return Entitlement(**{**base, **changes})


def test_the_plan_is_told_in_days() -> None:
    assert plan_line(entitlement(), NOW) == "Trial, 14 days left"
    assert plan_line(entitlement(plan_ends_at=NOW + timedelta(hours=5)), NOW) == "Trial, 1 day left"
    assert plan_line(entitlement(plan="paid"), NOW) == "Plan active"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PLURAL_DATA_DIR", str(tmp_path))
    return tmp_path


def test_login_without_a_code_says_where_to_get_one(home: Path) -> None:
    result = CliRunner().invoke(app, ["login"])
    assert result.exit_code == 2
    assert "plural login --code" in result.output


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
    service.answer = error(402, "trial_ended", "the free trial is over")
    result = CliRunner().invoke(app, ["login", "--code", "K7QF-29XD", "--accounts", ACCOUNTS])
    assert result.exit_code == 1
    assert "free trial is over" in result.output
