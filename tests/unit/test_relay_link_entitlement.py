import json
from collections.abc import AsyncIterator
from typing import Any

from plural.host.inbox import Inbox
from plural.host.transport.relay_link import RelayLink
from plural.protocol.relay import RelayOpen
from plural.security.keys import load_or_create_host_key
from plural.security.tokens import TokenSigner, TokenVerifier


class Socket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)

    def __aiter__(self) -> AsyncIterator[str]:
        return self._empty()

    async def _empty(self) -> AsyncIterator[str]:
        return
        yield


async def opening(tmp_path: Any, entitlement: Any) -> dict[str, Any]:
    signer = TokenSigner(load_or_create_host_key(tmp_path / "host_key"))
    link = RelayLink(url="wss://relay.example", room="r_1", signer=signer, entitlement=entitlement)
    socket = Socket()
    await link._session(socket, Inbox())  # pyright: ignore[reportPrivateUsage, reportArgumentType]
    return json.loads(socket.sent[0])


async def test_the_certificate_goes_with_the_opening(tmp_path: Any) -> None:
    async def certificate() -> str | None:
        return "body.signature"

    message = await opening(tmp_path, certificate)
    assert message["entitlement"] == "body.signature"
    assert TokenVerifier.from_b64(message["public_key"]).verify_proof(b"r_1", message["proof"])


async def test_a_host_without_an_account_opens_as_before(tmp_path: Any) -> None:
    async def nothing() -> str | None:
        return None

    assert (await opening(tmp_path, nothing))["entitlement"] is None
    assert (await opening(tmp_path, None))["entitlement"] is None


def test_a_relay_that_does_not_know_the_field_reads_the_opening_all_the_same() -> None:
    text = RelayOpen(room="r_1", public_key="k", proof="p", entitlement="c").model_dump_json()
    older = json.loads(text)
    older.pop("entitlement")
    assert RelayOpen.model_validate(older).entitlement is None
    assert RelayOpen.model_validate({**older, "future": 1}).room == "r_1"
