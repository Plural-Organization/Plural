"""The host hands its seat to a participant on another computer, through a relay (ADR 0019)."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from plural.client.connection import CommandRejected
from plural.client.reconnect import JoinLink, SessionClient
from plural.host.bootstrap import Host, build_host
from plural.host.config import HostSettings
from plural.host.handover import HandedAway
from plural.host.takeover import Takeover
from plural.protocol.commands import (
    HostHandoverAnswer,
    HostHandoverCancel,
    HostHandoverFetch,
    HostHandoverOffer,
    HostHandoverReady,
    PromptSubmit,
)
from plural.protocol.envelope import ErrorCode
from plural.protocol.events import (
    HostHandoverAccepted,
    HostHandoverChunk,
    HostHandoverEnded,
    HostHandoverGrant,
    HostHandoverOffered,
    RunEnded,
    SessionWelcome,
)
from plural.protocol.models import HOST_PARTICIPANT_ID, EntryKind, HandoverEnd, Role
from plural.security.seal import SealKey
from plural.security.tokens import TokenSigner
from tests.doubles import FakeProvider, reply
from tests.e2e.support import CLIENT, RelayServer, Watcher, free_port, running_session

# A session id has at least four characters after the r_, as the ones a real host makes do.
ROOM = "r_handover_e2e"


@dataclass(slots=True)
class Room:
    relay: RelayServer
    tmp: Path
    host: Host
    serving: asyncio.Task[None]
    watchers: list[Watcher]
    # Hosts that came up on other computers, closed with the room.
    later: list[Host] = field(default_factory=list[Host])

    async def watch(self, link: str, name: str) -> Watcher:
        watcher = Watcher(SessionClient(JoinLink.parse(link), name=name, client=CLIENT))
        self.watchers.append(watcher)
        await watcher.next(SessionWelcome)
        return watcher

    async def owner(self) -> Watcher:
        return await self.watch(self.host.host_link, "Bob")

    async def guest(self, name: str) -> Watcher:
        return await self.watch(self.host.invites.create(Role.PARTICIPANT, 600).link, name)

    def settings(self, who: str, **over: Any) -> HostSettings:
        workspace = self.tmp / f"ws_{who}"
        workspace.mkdir(exist_ok=True)
        return HostSettings(
            workspace=workspace,
            data_dir=self.tmp / f"data_{who}",
            port=free_port(),
            relay_url=self.relay.url,
            approval_timeout_s=30,
            provider="fake",
            host_name=who,
            **over,
        )


@pytest.fixture
async def room(tmp_path: Path) -> AsyncGenerator[Room]:
    relay = RelayServer()
    await relay.start()
    provider = FakeProvider([reply("the first host answers")])
    scratch = Room(relay, tmp_path, None, None, [])  # type: ignore[arg-type]
    host = await build_host(scratch.settings("Bob", room=ROOM), provider=provider)
    serving = asyncio.create_task(host.serve())
    scratch.host, scratch.serving = host, serving
    try:
        yield scratch
    finally:
        for watcher in scratch.watchers:
            await watcher.stop()
        for other in scratch.later:
            await other.close()
        serving.cancel()
        with suppress(asyncio.CancelledError, HandedAway):
            await serving
        await host.close()
        await relay.stop()


def token_of(watcher: Watcher) -> str:
    welcome = next(e for e in watcher.events if isinstance(e, SessionWelcome))
    return welcome.token


def link_for(room: Room, watcher: Watcher) -> str:
    return f"{room.relay.url}/{ROOM}?token={token_of(watcher)}"


def person(watcher: Watcher) -> str:
    me = watcher.client.projection.me
    assert me is not None
    return me.id


async def rejected(call: object) -> ErrorCode:
    with pytest.raises(CommandRejected) as caught:
        await call  # type: ignore[misc]
    return caught.value.error.code


async def offered(room: Room) -> tuple[Watcher, Watcher, Watcher]:
    owner = await room.owner()
    alia = await room.guest("Alia")
    cleo = await room.guest("Cleo")
    await cleo.client.send(PromptSubmit(text="what is in notes.txt"))
    await owner.next(RunEnded)
    await owner.client.send(HostHandoverOffer(participant_id=person(alia)))
    await alia.next(HostHandoverOffered)
    return owner, alia, cleo


async def test_the_host_offers_its_seat_and_everyone_sees_it(room: Room) -> None:
    owner, _, cleo = await offered(room)
    assert cleo.client.projection.state.handover is not None
    assert cleo.client.projection.state.handover.name == "Alia"
    assert not cleo.client.projection.state.handover.accepted
    await owner.client.send(HostHandoverCancel())
    ended = await cleo.next(HostHandoverEnded)
    assert ended.reason is HandoverEnd.CANCELLED
    assert cleo.client.projection.state.handover is None


async def test_only_the_host_offers_and_only_the_one_offered_answers(room: Room) -> None:
    owner, _, cleo = await offered(room)
    assert await rejected(cleo.client.send(HostHandoverOffer(participant_id=person(cleo)))) is (
        ErrorCode.FORBIDDEN
    )
    answer = HostHandoverAnswer(accept=True, seal_key="k" * 43, host_key="k" * 43)
    assert await rejected(cleo.client.send(answer)) is ErrorCode.FORBIDDEN
    assert await rejected(owner.client.send(HostHandoverOffer(participant_id=person(cleo)))) is (
        ErrorCode.CONFLICT
    )


async def test_declining_ends_the_offer(room: Room) -> None:
    owner, alia, _ = await offered(room)
    await alia.client.send(HostHandoverAnswer(accept=False))
    assert (await owner.next(HostHandoverEnded)).reason is HandoverEnd.DECLINED


async def test_a_viewer_cannot_be_offered_the_seat(room: Room) -> None:
    owner = await room.owner()
    viewer = await room.watch(room.host.invites.create(Role.VIEWER, 600).link, "Dee")
    assert await rejected(owner.client.send(HostHandoverOffer(participant_id=person(viewer)))) is (
        ErrorCode.INVALID
    )


async def test_the_seat_moves_to_another_computer_and_the_room_goes_on(room: Room) -> None:
    owner, alia, cleo = await offered(room)
    old_id = HOST_PARTICIPANT_ID
    alia_id = person(alia)

    taking = Takeover(link_for(room, alia), room.settings("Alia"))
    settings = await taking.receive()
    assert (await owner.next(HostHandoverAccepted)).participant_id == alia_id
    new_host = await build_host(settings, provider=FakeProvider([reply("the second host answers")]))
    room.later.append(new_host)
    await taking.finish(new_host)
    serving = asyncio.create_task(new_host.serve())
    try:
        # The first host finds the relay gave its room away, and stops.
        with pytest.raises(HandedAway):
            async with asyncio.timeout(15):
                await room.serving

        # Everyone still in the room comes back to the same link and finds the same conversation.
        async with asyncio.timeout(15):
            while cleo.client.projection.state.handovers != 1:
                await asyncio.sleep(0.05)
        state = cleo.client.projection.state
        assert state.participants[old_id].name == "Alia"
        assert state.participants[old_id].role is Role.HOST
        assert alia_id not in state.participants
        former = state.participants[taking.manifest.former_host_id]  # type: ignore[union-attr]
        assert (former.name, former.role) == ("Bob", Role.PARTICIPANT)
        # What the first host said stays the first host's; what Cleo asked stays Cleo's.
        said = [(e.kind, e.author_id) for e in state.transcript if e.kind is EntryKind.PROMPT]
        assert said == [(EntryKind.PROMPT, person(cleo))]
        assert any("the first host answers" in e.text for e in state.transcript)

        # Bob is a participant now: his old host token is his, and no longer the host's.
        async with asyncio.timeout(15):
            while owner.client.projection.me is None or owner.client.projection.me.id == old_id:
                await asyncio.sleep(0.05)
        assert owner.client.projection.me.role is Role.PARTICIPANT  # type: ignore[union-attr]

        # Alia is the host: her link opens the host's seat, and her host answers.
        boss = await room.watch(new_host.host_link, "Alia")
        assert boss.client.projection.me is not None
        assert boss.client.projection.me.id == old_id
        await boss.client.send(PromptSubmit(text="say hello"))
        await boss.next(RunEnded)
        assert "the second host answers" in " ".join(
            e.text for e in boss.client.projection.state.transcript
        )
    finally:
        serving.cancel()
        with suppress(asyncio.CancelledError, HandedAway):
            await serving


async def test_a_host_that_accepted_takes_no_new_work_and_a_lapsed_offer_ends(
    room: Room, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, alia, cleo = await offered(room)
    key = "k" * 43
    await alia.client.send(HostHandoverAnswer(accept=True, seal_key=key, host_key=key))
    await owner.next(HostHandoverAccepted)
    # Frozen: what the successor fetches is the whole log, so nothing new starts meanwhile.
    assert await rejected(cleo.client.send(PromptSubmit(text="one more thing"))) is (
        ErrorCode.CONFLICT
    )
    assert await rejected(owner.client.send(PromptSubmit(text="and from me"))) is ErrorCode.CONFLICT
    # The successor can still turn back, and then the host works again.
    await alia.client.send(HostHandoverCancel())
    assert (await owner.next(HostHandoverEnded)).reason is HandoverEnd.CANCELLED
    await cleo.client.send(PromptSubmit(text="now it works"))
    await owner.next(RunEnded)


async def test_an_offer_nobody_answers_is_taken_back(
    room: Room, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("plural.host.actor.OFFER_TTL", timedelta(milliseconds=300))
    owner = await room.owner()
    alia = await room.guest("Alia")
    await owner.client.send(HostHandoverOffer(participant_id=person(alia)))
    ended = await alia.next(HostHandoverEnded)
    assert ended.reason is HandoverEnd.EXPIRED
    assert owner.client.projection.state.handover is None


async def test_a_session_without_a_relay_cannot_be_handed_over(tmp_path: Path) -> None:
    async with running_session(tmp_path, relayed=False, provider=FakeProvider([])) as local:
        owner = await local.owner()
        alia = await local.guest("Alia")
        offer = HostHandoverOffer(participant_id=person(alia))
        assert await rejected(owner.client.send(offer)) is ErrorCode.CONFLICT


async def test_a_successor_that_never_opens_the_room_leaves_the_host_in_its_seat(
    room: Room, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The old host signed its word, and the new host did not come: it takes its seat back."""
    monkeypatch.setattr("plural.host.actor.GRANT_PATIENCE", timedelta(milliseconds=500))
    owner, alia, cleo = await offered(room)
    sealed, mine = SealKey(), TokenSigner(Ed25519PrivateKey.generate())
    await alia.client.send(
        HostHandoverAnswer(
            accept=True, seal_key=sealed.public_b64, host_key=mine.verifier.public_b64()
        )
    )
    await alia.client.send(HostHandoverFetch(part=0))
    chunk = await alia.next(HostHandoverChunk)
    assert chunk.parts >= 1
    await alia.client.send(HostHandoverReady())
    grant = await alia.next(HostHandoverGrant)
    assert grant.statement
    # She goes quiet. The old host waits out its patience, then ends the offer and works again.
    ended = await owner.next(HostHandoverEnded)
    assert ended.reason is HandoverEnd.EXPIRED
    assert cleo.client.projection.state.handover is None
    await cleo.client.send(PromptSubmit(text="still here"))
    await owner.next(RunEnded)
    assert not room.serving.done()
