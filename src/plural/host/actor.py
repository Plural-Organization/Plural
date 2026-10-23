import asyncio
import base64
import binascii
import hashlib
from pathlib import PurePath

import structlog
from pydantic import ValidationError

from plural.agent import events as agent
from plural.agent.messages import UserTurn
from plural.core import approvals, proposals
from plural.core.errors import Conflict, DomainError, Invalid, NotFound, Unauthorized
from plural.core.ports import Clock, EventStore, IdGenerator
from plural.core.provenance import direct, from_proposal
from plural.core.roles import authorize
from plural.core.state import reduce
from plural.host.agent_run import AgentRun
from plural.host.approval_registry import ApprovalRegistry
from plural.host.attachments import AttachmentVault
from plural.host.gateway import Gateway
from plural.host.inbox import (
    AgentOutput,
    ApprovalExpired,
    ApprovalNeeded,
    Disconnected,
    Inbox,
    InboxMessage,
    Incoming,
)
from plural.host.invites import InviteBook
from plural.host.publisher import Publisher
from plural.host.transport.base import Connection
from plural.protocol.codec import ProtocolError, decode_command
from plural.protocol.commands import (
    ApprovalRespond,
    Command,
    FileAttach,
    HistoryGet,
    InviteCreate,
    ParticipantRevoke,
    ParticipantSetRole,
    PromptSubmit,
    ProposalDecide,
    RunAbort,
    SessionHello,
)
from plural.protocol.envelope import Envelope, ErrorCode, ErrorInfo
from plural.protocol.events import (
    ApprovalRequested,
    AttachmentAdded,
    Event,
    InviteCreated,
    MessageDelta,
    MessageEnded,
    MessageStarted,
    ParticipantJoined,
    ParticipantLeft,
    ParticipantRevoked,
    ParticipantRoleChanged,
    PromptAccepted,
    ProposalApproved,
    RunEnded,
    RunStarted,
    SessionSnapshot,
    SessionWelcome,
    ToolEnded,
    ToolStarted,
)
from plural.protocol.models import (
    Actor,
    ActorKind,
    ApprovalDecision,
    AttachmentMeta,
    Delivery,
    Participant,
    Provenance,
    Role,
    RunEndReason,
    SessionState,
    Usage,
)
from plural.security.secrets import Redactor, is_denied_path

log = structlog.get_logger(__name__)


class SessionActor:
    def __init__(
        self,
        *,
        inbox: Inbox,
        store: EventStore,
        publisher: Publisher,
        gateway: Gateway,
        invites: InviteBook,
        agent_run: AgentRun,
        approval_registry: ApprovalRegistry,
        vault: AttachmentVault,
        redactor: Redactor,
        ids: IdGenerator,
        clock: Clock,
        host: Participant,
        max_attachment_bytes: int,
    ) -> None:
        self._inbox = inbox
        self._store = store
        self._publisher = publisher
        self._gateway = gateway
        self._invites = invites
        self._agent = agent_run
        self._registry = approval_registry
        self._vault = vault
        self._redactor = redactor
        self._ids = ids
        self._clock = clock
        self._host = host
        self._max_attachment_bytes = max_attachment_bytes
        self._state = SessionState()
        self._streaming: dict[str, str] = {}
        self._timers: dict[str, asyncio.TimerHandle] = {}

    @property
    def state(self) -> SessionState:
        return self._state

    async def start(self) -> None:
        for record in await self._store.read():
            self._state = reduce(self._state, record)
        for resolved in approvals.abandon_all(self._state):
            await self._emit(resolved)
        if self._state.run is not None:
            await self._emit(
                RunEnded(
                    run_id=self._state.run.id, reason=RunEndReason.ERROR, error="host restarted"
                )
            )
        for participant in self._state.participants.values():
            if participant.connected:
                await self._emit(ParticipantLeft(participant_id=participant.id))
        if self._host.id not in self._state.participants:
            await self._emit(ParticipantJoined(participant=self._host), actor_id=self._host.id)

    async def run(self) -> None:
        while True:
            message = await self._inbox.get()
            try:
                await self._handle(message)
            except Exception:
                log.exception("actor.message_failed", message=type(message).__name__)

    async def _handle(self, message: InboxMessage) -> None:
        match message:
            case Incoming(connection=connection, envelope=envelope):
                await self._on_envelope(connection, envelope)
            case Disconnected(connection=connection):
                await self._on_disconnect(connection)
            case AgentOutput(run_id=run_id, event=event):
                await self._on_agent(run_id, event)
            case ApprovalNeeded(approval=approval):
                await self._emit(ApprovalRequested(approval=approval))
                delay = max((approval.timeout_at - self._clock.now()).total_seconds(), 0)
                self._timers[approval.id] = asyncio.get_running_loop().call_later(
                    delay, self._inbox.put, ApprovalExpired(approval.id)
                )
            case ApprovalExpired(approval_id=approval_id):
                self._timers.pop(approval_id, None)
                expired = approvals.expire(self._state, approval_id)
                if expired is not None:
                    await self._emit(expired)
                    self._registry.resolve(approval_id, ApprovalDecision.REJECT)

    async def _on_envelope(self, connection: Connection, envelope: Envelope) -> None:
        try:
            command = decode_command(envelope)
            await self._dispatch(connection, envelope.token, command)
        except ValidationError as error:
            info = ErrorInfo(code=ErrorCode.INVALID, message=str(error.errors(include_url=False)))
            self._publisher.ack(connection, envelope.id, info)
        except (DomainError, ProtocolError) as error:
            self._publisher.ack(connection, envelope.id, error.info())
        else:
            self._publisher.ack(connection, envelope.id)

    async def _dispatch(self, connection: Connection, token: str | None, command: Command) -> None:
        if isinstance(command, SessionHello):
            await self._hello(connection, command)
            return
        participant = self._authenticate(connection, token)
        authorize(participant.role, command)
        match command:
            case HistoryGet():
                records = await self._store.read(before=command.before_seq, limit=command.limit)
                for record in records:
                    self._publisher.deliver_record(connection, record)
            case PromptSubmit():
                await self._submit(participant, command)
            case ProposalDecide():
                await self._decide(participant, command)
            case ApprovalRespond():
                resolved = approvals.resolve(
                    self._state,
                    approval_id=command.approval_id,
                    decision=command.decision,
                    resolved_by=participant.id,
                )
                await self._emit(resolved, actor_id=participant.id)
                self._cancel_timer(command.approval_id)
                self._registry.resolve(command.approval_id, command.decision)
            case RunAbort():
                if self._state.run is None:
                    raise Conflict("no active run")
                self._agent.abort()
            case InviteCreate():
                if command.role is Role.HOST:
                    raise Invalid("cannot invite another host")
                invite = self._invites.create(command.role, command.ttl_s)
                self._publisher.deliver(
                    connection,
                    InviteCreated(
                        code=invite.code,
                        role=invite.role,
                        expires_at=invite.expires_at,
                        link=invite.link,
                    ),
                )
            case ParticipantSetRole():
                self._require_guest(command.participant_id)
                await self._emit(
                    ParticipantRoleChanged(
                        participant_id=command.participant_id, role=command.role
                    ),
                    actor_id=participant.id,
                )
            case ParticipantRevoke():
                self._require_guest(command.participant_id)
                await self._emit(
                    ParticipantRevoked(participant_id=command.participant_id),
                    actor_id=participant.id,
                )
                self._publisher.disconnect(command.participant_id, "access revoked")
            case FileAttach():
                await self._attach(participant, command)

    async def _hello(self, connection: Connection, hello: SessionHello) -> None:
        admission = self._gateway.admit(hello, self._state)
        participant_id = admission.participant.id
        known = self._state.participants.get(participant_id, admission.participant)
        if not known.connected:
            joined = known.model_copy(update={"connected": True})
            await self._emit(ParticipantJoined(participant=joined), actor_id=participant_id)
        self._publisher.bind(connection, participant_id)
        welcome = SessionWelcome(
            room=self._publisher.room,
            token=admission.token,
            participant=self._state.participants[participant_id],
        )
        self._publisher.deliver(connection, welcome)
        if hello.since is None:
            snapshot = SessionSnapshot(state=self._state, streaming=dict(self._streaming))
            self._publisher.deliver(connection, snapshot)
            return
        for record in await self._store.read(after=hello.since):
            self._publisher.deliver_record(connection, record)

    def _authenticate(self, connection: Connection, token: str | None) -> Participant:
        if token is None:
            raise Unauthorized("token required")
        participant = self._gateway.identify(token, self._state)
        if self._publisher.participant_of(connection) != participant.id:
            raise Unauthorized("token is bound to another connection")
        return participant

    async def _submit(self, participant: Participant, command: PromptSubmit) -> None:
        if participant.role is Role.HOST:
            proposals.ensure_attachments(self._state, command.attachments)
            await self._accept(
                participant,
                text=command.text,
                delivery=command.delivery,
                attachments=command.attachments,
                provenance=direct(participant.id, participant.role),
            )
            return
        created = proposals.submit(
            self._state, proposal_id=self._ids.new("pr_"), author_id=participant.id, command=command
        )
        await self._emit(created, actor_id=participant.id)

    async def _decide(self, participant: Participant, command: ProposalDecide) -> None:
        proposal = self._state.proposals.get(command.proposal_id)
        decided = proposals.decide(self._state, decided_by=participant.id, command=command)
        await self._emit(decided, actor_id=participant.id)
        if proposal is None or not isinstance(decided, ProposalApproved):
            return
        author = self._state.participants.get(proposal.author_id) or Participant(
            id=proposal.author_id, name="former participant", role=Role.VIEWER
        )
        await self._accept(
            author,
            text=decided.text,
            delivery=proposal.delivery,
            attachments=proposal.attachments,
            provenance=from_proposal(author.id, author.role),
        )

    async def _accept(
        self,
        author: Participant,
        *,
        text: str,
        delivery: Delivery,
        attachments: tuple[str, ...],
        provenance: Provenance,
    ) -> None:
        prompt_id = self._ids.new("pm_")
        accepted = PromptAccepted(
            prompt_id=prompt_id,
            author_id=author.id,
            text=text,
            delivery=delivery,
            provenance=provenance,
            attachments=attachments,
        )
        await self._emit(accepted, actor_id=author.id)
        turn = UserTurn(
            id=prompt_id,
            author=Actor(id=author.id, kind=ActorKind.HUMAN, name=author.name),
            provenance=provenance,
            text=await self._with_attachments(text, attachments),
        )
        if self._state.run is None:
            await self._start_run(turn)
        elif delivery is Delivery.FOLLOW_UP:
            self._agent.follow_up(turn)
        else:
            self._agent.steer(turn)

    async def _start_run(self, turn: UserTurn) -> None:
        run_id = self._ids.new("run_")
        await self._emit(RunStarted(run_id=run_id, prompt_id=turn.id, provenance=turn.provenance))
        self._agent.start(run_id, turn)

    async def _on_agent(self, run_id: str, event: agent.AgentEvent) -> None:
        if self._state.run is None or self._state.run.id != run_id:
            return
        match event:
            case agent.MessageStart(message_id=message_id):
                self._streaming[message_id] = ""
                await self._emit(MessageStarted(run_id=run_id, message_id=message_id))
            case agent.MessageDelta(message_id=message_id, text=text, thinking=thinking):
                if not thinking:
                    self._streaming[message_id] = self._streaming.get(message_id, "") + text
                await self._emit(MessageDelta(message_id=message_id, text=text, thinking=thinking))
            case agent.MessageEnd(message_id=message_id, text=text, thinking=thinking):
                self._streaming.pop(message_id, None)
                await self._emit(
                    MessageEnded(run_id=run_id, message_id=message_id, text=text, thinking=thinking)
                )
            case agent.ToolStart(call=call):
                await self._emit(ToolStarted(run_id=run_id, call=call))
            case agent.ToolEnd(call_id=call_id, result=result):
                await self._emit(
                    ToolEnded(
                        run_id=run_id,
                        call_id=call_id,
                        ok=not result.is_error,
                        output=result.content,
                        diff=result.diff,
                    )
                )
            case agent.RunEnd(reason=reason, usage=usage, error=error):
                await self._finish_run(run_id, reason, usage, error)

    async def _finish_run(
        self, run_id: str, reason: RunEndReason, usage: Usage, error: str | None
    ) -> None:
        for resolved in approvals.abandon_all(self._state):
            self._cancel_timer(resolved.approval_id)
            self._registry.resolve(resolved.approval_id, ApprovalDecision.REJECT)
            await self._emit(resolved)
        self._streaming.clear()
        await self._emit(RunEnded(run_id=run_id, reason=reason, usage=usage, error=error))
        pending = self._agent.drain_pending()
        if reason is RunEndReason.ABORTED or not pending:
            return
        first, *rest = pending
        await self._start_run(first)
        for turn in rest:
            self._agent.follow_up(turn)

    async def _on_disconnect(self, connection: Connection) -> None:
        participant_id = self._publisher.unbind(connection)
        if participant_id is None or self._publisher.is_online(participant_id):
            return
        if participant_id in self._state.participants:
            await self._emit(
                ParticipantLeft(participant_id=participant_id), actor_id=participant_id
            )

    async def _attach(self, participant: Participant, command: FileAttach) -> None:
        if is_denied_path(PurePath(command.name)):
            raise Invalid(f"{command.name} looks like a secret file")
        try:
            data = base64.b64decode(command.content_b64, validate=True)
        except binascii.Error as error:
            raise Invalid("content is not valid base64") from error
        if len(data) > self._max_attachment_bytes:
            raise Invalid(f"attachment exceeds {self._max_attachment_bytes} bytes")
        if hashlib.sha256(data).hexdigest() != command.sha256:
            raise Invalid("sha256 mismatch")
        attachment_id = self._ids.new("at_")
        await self._vault.save(attachment_id, data)
        meta = AttachmentMeta(
            id=attachment_id,
            name=command.name,
            size=len(data),
            sha256=command.sha256,
            owner_id=participant.id,
        )
        await self._emit(AttachmentAdded(attachment=meta), actor_id=participant.id)

    async def _with_attachments(self, text: str, attachment_ids: tuple[str, ...]) -> str:
        parts = [text]
        for attachment_id in attachment_ids:
            meta = self._state.attachments[attachment_id]
            body = await self._vault.read_text(attachment_id)
            parts.append(f"[attachment {meta.name}, untrusted]\n{body}")
        return "\n\n".join(parts)

    def _require_guest(self, participant_id: str) -> None:
        target = self._state.participants.get(participant_id)
        if target is None:
            raise NotFound(f"participant {participant_id}")
        if target.role is Role.HOST:
            raise Conflict("host role cannot be changed")

    def _cancel_timer(self, approval_id: str) -> None:
        timer = self._timers.pop(approval_id, None)
        if timer is not None:
            timer.cancel()

    async def _emit(self, event: Event, *, actor_id: str | None = None) -> None:
        event = self._redactor.scrub(event)
        if not event.durable:
            self._publisher.publish_transient(event, actor_id=actor_id)
            return
        record = await self._store.append(
            event, event_id=self._ids.new("e_"), ts=self._clock.now(), actor_id=actor_id
        )
        self._state = reduce(self._state, record)
        self._publisher.publish(record)
