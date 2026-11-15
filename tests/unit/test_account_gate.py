"""A host asks the relay whether it needs an account before it opens a room (ADR 0017)."""

import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request

import pytest
from typer.testing import CliRunner
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from plural.cli import main
from plural.host import account_gate
from plural.host.account import AccountStore, Entitlement
from plural.host.account_gate import AccountRequired, ensure_signed_in
from plural.host.config import HostSettings
from plural.host.transport.relay_link import _account_refusal  # pyright: ignore[reportPrivateUsage]

RELAY = "wss://relay.example"


class _Reply(io.BytesIO):
    def __enter__(self) -> "_Reply":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def healthz(monkeypatch: pytest.MonkeyPatch, answer: object) -> list[str]:
    asked: list[str] = []

    def fake(request: Request, *, timeout: float) -> Any:
        asked.append(request.full_url)
        if isinstance(answer, Exception):
            raise answer
        return _Reply(json.dumps(answer).encode() if not isinstance(answer, bytes) else answer)

    monkeypatch.setattr(account_gate, "urlopen", fake)
    return asked


def settings(tmp_path: Path, relay: str | None = RELAY) -> HostSettings:
    return HostSettings(data_dir=tmp_path, relay_url=relay)


def sign_in(tmp_path: Path, *, expires: timedelta = timedelta(days=5)) -> None:
    AccountStore(tmp_path).save(
        Entitlement(
            accounts="https://accounts.example",
            email="alia@example.com",
            certificate="body.signature",
            expires_at=datetime.now(UTC) + expires,
        )
    )


async def test_a_relay_that_needs_an_account_stops_a_host_that_has_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = healthz(monkeypatch, {"ok": True, "accounts": "required"})
    with pytest.raises(AccountRequired, match="plural login"):
        await ensure_signed_in(settings(tmp_path))
    assert asked == ["https://relay.example/healthz"]


async def test_a_signed_in_host_goes_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    healthz(monkeypatch, {"ok": True, "accounts": "required"})
    sign_in(tmp_path)
    await ensure_signed_in(settings(tmp_path))


async def test_a_certificate_that_ran_out_and_could_not_be_renewed_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    healthz(monkeypatch, {"ok": True, "accounts": "required"})
    sign_in(tmp_path, expires=timedelta(days=-1))

    async def cannot_renew(*_: object) -> None:
        raise TimeoutError

    monkeypatch.setattr("plural.host.account.renew", cannot_renew)
    with pytest.raises(AccountRequired, match="expired"):
        await ensure_signed_in(settings(tmp_path))


async def test_a_relay_that_does_not_ask_is_never_in_the_way(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    healthz(monkeypatch, {"ok": True})
    await ensure_signed_in(settings(tmp_path))


@pytest.mark.parametrize(
    "answer",
    [URLError("offline"), OSError("refused"), b"<html>not json</html>", b"[1, 2]", b'"yes"'],
)
async def test_what_cannot_be_read_does_not_stop_a_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer: object
) -> None:
    # The relay judges the host itself when the room opens; this check only saves it a silent retry.
    healthz(monkeypatch, answer)
    await ensure_signed_in(settings(tmp_path))


async def test_a_host_with_no_relay_asks_nobody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = healthz(monkeypatch, {"ok": True, "accounts": "required"})
    await ensure_signed_in(settings(tmp_path, relay=None))
    assert asked == []


def test_the_host_command_prints_why_on_stderr_and_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    async def refused(_settings: HostSettings, *, machine: bool) -> None:
        raise AccountRequired(account_gate.SIGN_IN)

    monkeypatch.setattr(main, "_host", refused)
    result = CliRunner().invoke(main.app, ["host", "--json", "--relay", RELAY])
    assert result.exit_code == 1
    assert "plural login" in result.stderr
    assert "plural login" not in result.stdout


def _closed(code: int, reason: str) -> ConnectionClosedError:
    return ConnectionClosedError(Close(code, reason), None)


def test_a_host_tells_an_account_refusal_from_any_other_disconnect() -> None:
    assert _account_refusal(_closed(4402, "run plural login")) == "run plural login"
    assert _account_refusal(_closed(4403, "")) is not None
    # Limits, a taken room and a restart are not about the account; 4503 is worth a quick retry.
    for code in (1011, 4401, 4409, 4429, 4503):
        assert _account_refusal(_closed(code, "x")) is None
    assert _account_refusal(OSError("down")) is None
