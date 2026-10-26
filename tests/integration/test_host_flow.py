import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from plural.agent.providers.fake import FakeProvider, reply, use_tool
from plural.host.bootstrap import Host, build_host
from plural.host.config import HostSettings
from plural.host.inbox import Disconnected, Incoming
from plural.protocol.codec import decode_event, encode_command
from plural.protocol.commands import (
    ApprovalRespond,
    ClientInfo,
    Command,
    ParticipantRevoke,
    PromptSubmit,
    ProposalDecide,
    SessionHello,
)
from plural.protocol.envelope import Envelope, ErrorCode, Kind
from plural.protocol.events import (
    ApprovalRequested,
    Event,
    PromptAccepted,
    ProposalCreated,
    RunEnded,
    SessionSnapshot,
    SessionWelcome,
    ToolEnded,
)
from plural.protocol.models import ApprovalDecision, Origin, PromptMode, ProposalDecision, Role

CLIENT = ClientInfo(kind="test", version="0")


class MemoryConnection:
    def __init__(self, connection_id: str) -> None:
        self._id = connection_id
        self.sent: list[Envelope] = []
        self.closed: str | None = None
        self.token: str | None = None
        self._counter = 0

    @property
    def id(self) -> str:
        return self._id

    def send(self, envelope: Envelope) -> None:
        self.sent.append(envelope)

    def close(self, reason: str) -> None:
        self.closed = reason

    def events(self) -> list[Event]:
        return [decode_event(e) for e in self.sent if e.kind is Kind.EVT]

    def first[E](self, kind: type[E]) -> E | None:
        return next((e for e in self.events() if isinstance(e, kind)), None)

    def ack_for(self, envelope_id: str) -> Envelope | None:
        return next((e for e in self.sent if e.kind is Kind.ACK and e.re == envelope_id), None)

    def command(self, command: Command) -> Envelope:
        self._counter += 1
        return encode_command(
            command,
            envelope_id=f"{self._id}_{self._counter}",
            room="r_test",
            ts=datetime.now(UTC),
            token=self.token,
        )


async def eventually(predicate: Callable[[], object], timeout: float = 3.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


@pytest.fixture
async def host(tmp_path: Path) -> AsyncIterator[Host]:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("hello from notes\n")
    provider = FakeProvider([use_tool("bash", command="cat notes.txt"), reply("All good.")])
    settings = HostSettings(
        workspace=workspace,
        data_dir=tmp_path / "data",
        room="r_test",
        prompt_mode=PromptMode.REVIEW,
    )
    plural_host = await build_host(settings, provider=provider)
    task = asyncio.create_task(plural_host.actor.run())
    yield plural_host
    task.cancel()
    await plural_host.close()


async def connect(host: Host, connection: MemoryConnection, hello: SessionHello) -> SessionWelcome:
    host.inbox.put(Incoming(connection, connection.command(hello)))
    await eventually(lambda: connection.first(SessionWelcome))
    welcome = connection.first(SessionWelcome)
    assert welcome is not None
    connection.token = welcome.token
    return welcome


def send(host: Host, connection: MemoryConnection, command: Command) -> str:
    envelope = connection.command(command)
    host.inbox.put(Incoming(connection, envelope))
    return envelope.id


async def test_guest_proposal_to_approved_tool_call(host: Host) -> None:
    owner = MemoryConnection("c_host")
    await connect(host, owner, SessionHello(client=CLIENT, token=host.host_token))
    invite = host.invites.create(Role.PARTICIPANT, 600)
    guest = MemoryConnection("c_guest")
    welcome = await connect(
        host, guest, SessionHello(client=CLIENT, invite=invite.code, name="Alia")
    )
    assert guest.first(SessionSnapshot) is not None

    send(host, guest, PromptSubmit(text="check the notes"))
    await eventually(lambda: owner.first(ProposalCreated))
    created = owner.first(ProposalCreated)
    assert created is not None

    send(
        host,
        owner,
        ProposalDecide(proposal_id=created.proposal.id, decision=ProposalDecision.APPROVE),
    )
    await eventually(lambda: owner.first(ApprovalRequested))
    requested = owner.first(ApprovalRequested)
    assert requested is not None
    assert requested.approval.provenance.origin is Origin.PROPOSAL

    forbidden = send(
        host,
        guest,
        ApprovalRespond(approval_id=requested.approval.id, decision=ApprovalDecision.ONCE),
    )
    await eventually(lambda: guest.ack_for(forbidden))
    ack = guest.ack_for(forbidden)
    assert ack is not None
    assert ack.error is not None
    assert ack.error.code is ErrorCode.FORBIDDEN

    send(
        host,
        owner,
        ApprovalRespond(approval_id=requested.approval.id, decision=ApprovalDecision.ONCE),
    )
    await eventually(lambda: guest.first(RunEnded))
    tool = guest.first(ToolEnded)
    assert tool is not None
    assert "hello from notes" in tool.output
    accepted = guest.first(PromptAccepted)
    assert accepted is not None
    assert accepted.author_id == welcome.participant.id


async def test_revoked_guest_loses_access(host: Host) -> None:
    owner = MemoryConnection("c_host")
    await connect(host, owner, SessionHello(client=CLIENT, token=host.host_token))
    invite = host.invites.create(Role.PARTICIPANT, 600)
    guest = MemoryConnection("c_guest")
    welcome = await connect(
        host, guest, SessionHello(client=CLIENT, invite=invite.code, name="Bek")
    )

    send(host, owner, ParticipantRevoke(participant_id=welcome.participant.id))
    await eventually(lambda: guest.closed)
    host.inbox.put(Disconnected(guest))

    retry = MemoryConnection("c_guest_retry")
    attempt = send(host, retry, SessionHello(client=CLIENT, token=welcome.token))
    await eventually(lambda: retry.ack_for(attempt))
    ack = retry.ack_for(attempt)
    assert ack is not None
    assert ack.error is not None
    assert ack.error.code is ErrorCode.UNAUTHORIZED


async def test_reconnect_replays_since(host: Host) -> None:
    owner = MemoryConnection("c_host")
    await connect(host, owner, SessionHello(client=CLIENT, token=host.host_token))
    last_seq = host.actor.state.last_seq
    host.inbox.put(Disconnected(owner))
    send(host, owner, PromptSubmit(text="x"))
    again = MemoryConnection("c_host_2")
    again.token = host.host_token
    send(host, again, SessionHello(client=CLIENT, token=host.host_token, since=last_seq))
    await eventually(lambda: any(e.seq and e.seq > last_seq for e in again.sent))
    assert again.first(SessionSnapshot) is None
