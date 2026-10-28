import asyncio
import base64
import binascii
import hashlib
from collections.abc import Coroutine, Sequence
from dataclasses import dataclass
from pathlib import PurePath

import structlog
from pydantic import ValidationError

from plural.agent import events as agent
from plural.agent.mcp import McpError, McpHub, ServerSpec
from plural.agent.messages import Message, UserTurn
from plural.agent.providers.base import LlmImage
from plural.agent.skills import Package, SkillError, SkillLibrary, parse_package
from plural.core import approvals, chat, joins, policies, proposals, visibility
from plural.core.errors import (
    Conflict,
    DomainError,
    Forbidden,
    Invalid,
    NotFound,
    Unauthorized,
)
from plural.core.ports import Clock, EventStore, IdGenerator
from plural.core.provenance import direct, from_proposal
from plural.core.roles import authorize
from plural.core.state import reduce
from plural.host import history
from plural.host.agent_run import AgentRun
from plural.host.approval_registry import ApprovalRegistry
from plural.host.attachments import AttachmentVault, image_type
from plural.host.gateway import Admission, Gateway, NeedsApproval
from plural.host.inbox import (
    AgentOutput,
    ApprovalExpired,
    ApprovalNeeded,
    Disconnected,
    Inbox,
    InboxMessage,
    Incoming,
    JoinExpired,
    McpUpdated,
    Reconfigure,
    SkillsReply,
    SkillsUpdated,
    TypingExpired,
)
from plural.host.invites import InviteBook, RoomLink
from plural.host.policy_gate import HostPolicyGate
from plural.host.publisher import Publisher
from plural.host.transport.base import Connection
from plural.protocol.codec import ProtocolError, decode_command
from plural.protocol.commands import (
    AdmissionSet,
    ApprovalRespond,
    BoardClear,
    BoardDraw,
    BoardErase,
    BoardOpen,
    ChatSend,
    Command,
    ContextCompact,
    CursorSet,
    FileAttach,
    HistoryGet,
    InviteCreate,
    JoinDecide,
    LinkRevoke,
    McpAdd,
    McpImport,
    McpRemove,
    McpRestart,
    McpToggle,
    ParticipantRevoke,
    ParticipantSetRole,
    PermissionModeSet,
    PolicyAdd,
    PolicyRemove,
    PromptModeSet,
    PromptSubmit,
    ProposalDecide,
    QueueCancel,
    RunAbort,
    SelectionSet,
    SessionHello,
    SkillsInstall,
    SkillsRemove,
    SkillsSearch,
    TypingSet,
)
from plural.protocol.envelope import Envelope, ErrorCode, ErrorInfo
from plural.protocol.events import (
    AgentChanged,
    ApprovalRequested,
    AttachmentAdded,
    BoardCleared,
    BoardErased,
    BoardOpened,
    BoardStroked,
    ContextCompacted,
    ContextCompacting,
    ContextUsage,
    ErrorRaised,
    Event,
    EventRecord,
    InviteCreated,
    JoinPending,
    JoinRefused,
    McpChanged,
    MessageDelta,
    MessageEnded,
    MessageStarted,
    ParticipantCursor,
    ParticipantJoined,
    ParticipantLeft,
    ParticipantRevoked,
    ParticipantRoleChanged,
    ParticipantSelected,
    ParticipantTyping,
    PermissionModeChanged,
    PolicyRuleAdded,
    PolicyRuleRemoved,
    PromptAccepted,
    PromptDequeued,
    PromptModeChanged,
    ProposalApproved,
    RunEnded,
    RunStarted,
    SessionSnapshot,
    SessionWelcome,
    SkillsChanged,
    SkillsFound,
    ToolEnded,
    ToolOutput,
    ToolStarted,
)
from plural.protocol.models import (
    BOARD_DECIMALS,
    Actor,
    ActorKind,
    AdmissionMode,
    ApprovalDecision,
    AttachmentMeta,
    BoardShape,
    BoardStroke,
    ContextView,
    Delivery,
    DequeueReason,
    JoinDecision,
    Participant,
    PermissionMode,
    PromptMode,
    Provenance,
    Role,
    RunEndReason,
    SessionState,
    SkillScope,
    Usage,
)
from plural.security.secrets import Redactor, is_denied_path

log = structlog.get_logger(__name__)

PLAN_NOTE = (
    "[plan mode: research only. Read the code, do not change files or run commands that change "
    "anything. End with a concrete step-by-step plan; the host approves it before you start]"
)


@dataclass(slots=True)
class Knock:
    request_id: str
    connection: Connection
    name: str
    timer: asyncio.TimerHandle


class SessionActor:
    def __init__(
        self,
        *,
        inbox: Inbox,
        store: EventStore,
        publisher: Publisher,
        gateway: Gateway,
        invites: InviteBook,
        link: RoomLink,
        agent_run: AgentRun,
        approval_registry: ApprovalRegistry,
        gate: HostPolicyGate,
        vault: AttachmentVault,
        redactor: Redactor,
        ids: IdGenerator,
        clock: Clock,
        host: Participant,
        max_attachment_bytes: int,
        max_image_bytes: int,
        prompt_mode: PromptMode | None = None,
        admission: AdmissionMode | None = None,
        skills: SkillLibrary | None = None,
        mcp: McpHub | None = None,
        typing_ttl_s: float = 6.0,
        agent_label: str = "",
        join_timeout_s: float = 120.0,
        max_pending_joins: int = 5,
        max_participants: int = 20,
    ) -> None:
        self._inbox = inbox
        self._store = store
        self._publisher = publisher
        self._gateway = gateway
        self._invites = invites
        self._link = link
        self._join_timeout_s = join_timeout_s
        self._max_pending_joins = max_pending_joins
        self._max_participants = max_participants
        self._knocking: dict[str, Knock] = {}
        self._agent = agent_run
        self._registry = approval_registry
        self._gate = gate
        self._vault = vault
        self._redactor = redactor
        self._ids = ids
        self._clock = clock
        self._host = host
        self._max_attachment_bytes = max_attachment_bytes
        self._max_image_bytes = max_image_bytes
        self._initial_mode = prompt_mode
        self._initial_admission = admission
        self._skills = skills
        self._mcp = mcp
        self._jobs: set[asyncio.Task[None]] = set()
        self._typing_ttl_s = typing_ttl_s
        self._agent_label = agent_label
        self._typing: dict[str, asyncio.TimerHandle] = {}
        self._selecting: set[str] = set()
        self._pointing: set[str] = set()
        self._state = SessionState()
        self._streaming: dict[str, str] = {}
        self._timers: dict[str, asyncio.TimerHandle] = {}

    @property
    def state(self) -> SessionState:
        return self._state

    async def start(self) -> None:
        records = await self._store.read()
        for record in records:
            self._state = reduce(self._state, record)
        self._sync_policy()
        if conversation := await self._history(records):
            self._agent.restore(conversation)
        for resolved in approvals.abandon_all(self._state):
            await self._emit(resolved)
        for left_waiting in joins.abandon_all(self._state, JoinDecision.EXPIRED):
            await self._emit(left_waiting)
        if self._state.run is not None:
            await self._emit(
                RunEnded(
                    run_id=self._state.run.id, reason=RunEndReason.ERROR, error="host restarted"
                )
            )
        for entry in self._state.queue:
            await self._emit(
                PromptDequeued(prompt_id=entry.prompt_id, reason=DequeueReason.DROPPED)
            )
        for participant in self._state.participants.values():
            if participant.connected:
                await self._emit(ParticipantLeft(participant_id=participant.id))
        if self._host.id not in self._state.participants:
            await self._emit(ParticipantJoined(participant=self._host), actor_id=self._host.id)
        if self._agent_label and self._state.agent != self._agent_label:
            await self._emit(AgentChanged(agent=self._agent_label), actor_id=self._host.id)
        if self._initial_mode is not None:
            await self._set_prompt_mode(self._initial_mode, actor_id=self._host.id)
        if self._initial_admission is not None:
            changed = joins.set_admission(self._state, self._initial_admission)
            if changed is not None:
                await self._emit(changed, actor_id=self._host.id)
        await self._set_permission_mode(PermissionMode.DEFAULT, actor_id=self._host.id)
        if self._skills is not None:
            await self._skills.refresh()
            await self._sync_skills()
        await self._sync_context(self._agent.fill())
        await self._sync_mcp()

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
            case Reconfigure() as change:
                await self._reconfigure(change)
            case McpUpdated():
                await self._sync_mcp()
            case SkillsUpdated(connection=connection, error=error):
                await self._sync_skills()
                if error is not None and connection is not None:
                    self._publisher.deliver(
                        connection, ErrorRaised(code=ErrorCode.INVALID, message=error)
                    )
            case SkillsReply(connection=connection, event=found, error=error):
                self._publisher.deliver(
                    connection,
                    found or ErrorRaised(code=ErrorCode.INVALID, message=error or "search failed"),
                )
            case JoinExpired(request_id=request_id):
                await self._expire_join(request_id)
            case TypingExpired(participant_id=participant_id):
                if self._typing.pop(participant_id, None) is not None:
                    await self._emit(ParticipantTyping(participant_id=participant_id, typing=False))
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
            case ChatSend():
                await self._emit(
                    chat.post(
                        self._state,
                        message_id=self._ids.new("c_"),
                        author=participant,
                        command=command,
                    ),
                    actor_id=participant.id,
                )
            case ProposalDecide():
                await self._decide(participant, command)
            case ApprovalRespond():
                resolved = approvals.resolve(
                    self._state,
                    approval_id=command.approval_id,
                    decision=command.decision,
                    resolved_by=participant.id,
                )
                remembered = policies.from_decision(
                    self._state, approval_id=command.approval_id, decision=command.decision
                )
                await self._emit(resolved, actor_id=participant.id)
                for tool, pattern, action in remembered:
                    if not policies.in_effect(self._state, tool, pattern, action):
                        rule = policies.add(
                            self._state,
                            rule_id=self._ids.new("pl_"),
                            tool=tool,
                            pattern=pattern,
                            action=action,
                        )
                        await self._emit(rule, actor_id=participant.id)
                self._cancel_timer(command.approval_id)
                self._registry.resolve(command.approval_id, command.decision)
            case RunAbort():
                if self._state.run is None:
                    raise Conflict("no active run")
                self._agent.abort()
            case ContextCompact():
                if self._state.run is not None:
                    self._agent.request_compaction()
                elif not self._agent.can_compact:
                    raise Conflict("nothing to compact yet")
                else:
                    run_id = self._ids.new("run_")
                    provenance = direct(participant.id, participant.role)
                    await self._emit(
                        RunStarted(run_id=run_id, prompt_id="", provenance=provenance),
                        actor_id=participant.id,
                    )
                    self._agent.compact(run_id)
            case PromptModeSet():
                await self._set_prompt_mode(command.mode, actor_id=participant.id)
            case PermissionModeSet():
                await self._set_permission_mode(command.mode, actor_id=participant.id)
            case McpAdd() | McpRemove() | McpToggle() | McpRestart() | McpImport():
                await self._mcp_command(command, actor_id=participant.id)
            case SkillsSearch():
                self._background(self._search_skills(connection, command.query))
            case SkillsInstall():
                try:
                    package = parse_package(command.package)
                except SkillError as error:
                    raise Invalid(str(error)) from None
                self._background(self._install_skill(connection, package, command.scope))
            case SkillsRemove():
                try:
                    await self._library().remove(command.name)
                except SkillError as error:
                    raise NotFound(str(error)) from None
                await self._sync_skills(actor_id=participant.id)
            case TypingSet():
                await self._set_typing(participant.id, typing=command.typing)
            case SelectionSet():
                await self._set_selection(participant.id, command)
            case CursorSet():
                await self._set_cursor(participant.id, command)
            case BoardOpen():
                # Opening again shows the board to everyone again; closing twice says nothing.
                if command.open or self._state.board.open:
                    await self._emit(
                        BoardOpened(open=command.open, by=participant.id), actor_id=participant.id
                    )
            case BoardDraw():
                if len(command.points) % 2 != 0:
                    raise Invalid("a stroke needs x and y for every point")
                if command.kind is BoardShape.TEXT:
                    if not command.text or len(command.points) != 2:
                        raise Invalid("a text needs its words and one point")
                elif command.text is not None:
                    raise Invalid("only a text carries words")
                elif command.kind is not BoardShape.PEN and len(command.points) != 4:
                    raise Invalid("a shape needs its two corners")
                stroke = BoardStroke(
                    id=self._ids.new("st_"),
                    author_id=participant.id,
                    kind=command.kind,
                    text=command.text,
                    color=command.color,
                    width=command.width,
                    points=tuple(round(point, BOARD_DECIMALS) for point in command.points),
                )
                await self._emit(BoardStroked(stroke=stroke), actor_id=participant.id)
            case BoardErase():
                stroke = next(
                    (s for s in self._state.board.strokes if s.id == command.stroke_id), None
                )
                if stroke is None:
                    raise NotFound("no such stroke on the board")
                if stroke.author_id != participant.id and participant.role is not Role.HOST:
                    raise Forbidden("only the host erases someone else's drawing")
                await self._emit(BoardErased(stroke_id=stroke.id), actor_id=participant.id)
            case BoardClear():
                if self._state.board.strokes:
                    await self._emit(BoardCleared(by=participant.id), actor_id=participant.id)
            case QueueCancel():
                await self._cancel_queued(participant, command)
            case PolicyAdd():
                added = policies.add(
                    self._state,
                    rule_id=self._ids.new("pl_"),
                    tool=command.tool,
                    pattern=command.pattern,
                    action=command.action,
                )
                await self._emit(added, actor_id=participant.id)
            case PolicyRemove():
                await self._emit(
                    policies.remove(self._state, command.rule_id), actor_id=participant.id
                )
            case InviteCreate():
                if command.role is Role.HOST:
                    raise Invalid("cannot invite another host")
                if command.reusable:
                    self._publisher.deliver(connection, self._room_link_event())
                    return
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
            case JoinDecide():
                await self._decide_join(participant, command)
            case LinkRevoke():
                await self._revoke_link(participant)
                self._publisher.deliver(connection, self._room_link_event())
            case AdmissionSet():
                changed = joins.set_admission(self._state, command.mode)
                if changed is not None:
                    await self._emit(changed, actor_id=participant.id)
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
        if isinstance(admission, NeedsApproval):
            await self._knock(connection, admission)
            return
        await self._welcome(connection, admission, since=hello.since)

    async def _welcome(
        self, connection: Connection, admission: Admission, *, since: int | None
    ) -> None:
        participant_id = admission.participant.id
        known = self._state.participants.get(participant_id)
        if known is None and self._connected() >= self._max_participants:
            raise Forbidden("the room is full")
        known = known or admission.participant
        if not known.connected:
            joined = known.model_copy(update={"connected": True})
            await self._emit(ParticipantJoined(participant=joined), actor_id=participant_id)
        self._publisher.bind(connection, participant_id)
        welcome = SessionWelcome(
            room=self._publisher.room,
            token=admission.token,
            participant=self._state.participants[participant_id],
            base_policy=policies.to_views(self._gate.policy.rules, prefix="base"),
            agent=self._agent_label,
        )
        self._publisher.deliver(connection, welcome)
        if since is None:
            snapshot = SessionSnapshot(
                state=visibility.state_for(self._state, participant_id),
                streaming=dict(self._streaming),
                typing=tuple(self._typing),
            )
            self._publisher.deliver(connection, snapshot)
            return
        for record in await self._store.read(after=since):
            self._publisher.deliver_record(connection, record)

    def _connected(self) -> int:
        return sum(1 for person in self._state.participants.values() if person.connected)

    def _room_link_event(self) -> InviteCreated:
        return InviteCreated(
            code=self._link.code,
            role=Role.PARTICIPANT,
            expires_at=None,
            link=self._link.link,
            reusable=True,
        )

    def _refuse(self, connection: Connection, reason: str) -> None:
        self._publisher.deliver(connection, JoinRefused(reason=reason))
        connection.close(reason)

    async def _knock(self, connection: Connection, need: NeedsApproval) -> None:
        if connection.id in self._knocking:
            return
        try:
            asked = joins.request(
                self._state,
                request_id=self._ids.new("j_"),
                name=need.name,
                client=need.client,
                now=self._clock.now(),
                limit=self._max_pending_joins,
            )
        except Conflict as error:
            raise Forbidden(str(error)) from error
        await self._emit(asked)
        request_id = asked.request.id
        timer = asyncio.get_running_loop().call_later(
            self._join_timeout_s, self._inbox.put, JoinExpired(request_id)
        )
        self._knocking[connection.id] = Knock(request_id, connection, need.name, timer)
        self._publisher.deliver(connection, JoinPending(waiting=len(self._knocking)))

    def _take_knock(self, request_id: str) -> Knock | None:
        for connection_id, knock in self._knocking.items():
            if knock.request_id == request_id:
                knock.timer.cancel()
                return self._knocking.pop(connection_id)
        return None

    async def _decide_join(self, host: Participant, command: JoinDecide) -> None:
        decision = {
            "allow": JoinDecision.ALLOW,
            "viewer": JoinDecision.VIEWER,
            "deny": JoinDecision.DENY,
        }[command.decision]
        resolved = joins.resolve(self._state, command.request_id, decision, host.id)
        knock = self._take_knock(command.request_id)
        await self._emit(resolved, actor_id=host.id)
        if knock is None:
            return
        if decision is JoinDecision.DENY:
            self._refuse(knock.connection, "the host did not let you in")
            return
        role = Role.VIEWER if decision is JoinDecision.VIEWER else Role.PARTICIPANT
        try:
            await self._welcome(
                knock.connection, self._gateway.admit_approved(knock.name, role), since=None
            )
        except DomainError as error:
            self._refuse(knock.connection, str(error))

    async def _expire_join(self, request_id: str) -> None:
        knock = self._take_knock(request_id)
        if request_id not in self._state.join_requests:
            return
        await self._emit(joins.resolve(self._state, request_id, JoinDecision.EXPIRED, None))
        if knock is not None:
            self._refuse(knock.connection, "the host did not answer in time, ask them again")

    async def _revoke_link(self, host: Participant) -> None:
        code = self._link.rotate()
        await self._store.set_meta("room_link", code)
        for request_id in list(self._state.join_requests):
            knock = self._take_knock(request_id)
            await self._emit(
                joins.resolve(self._state, request_id, JoinDecision.REVOKED, host.id),
                actor_id=host.id,
            )
            if knock is not None:
                self._refuse(knock.connection, "this room link was withdrawn by the host")

    def _authenticate(self, connection: Connection, token: str | None) -> Participant:
        if token is None:
            raise Unauthorized("token required")
        participant = self._gateway.identify(token, self._state)
        if self._publisher.participant_of(connection) != participant.id:
            raise Unauthorized("token is bound to another connection")
        return participant

    async def _submit(self, participant: Participant, command: PromptSubmit) -> None:
        if participant.role is Role.HOST or self._state.prompt_mode is PromptMode.OPEN:
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

    async def _reconfigure(self, change: Reconfigure) -> None:
        if self._state.run is not None:
            change.reply.set_exception(
                Conflict("the agent is busy, wait for the current run to end")
            )
            return
        self._agent.swap_provider(change.provider, context_window=change.context_window)
        for secret in change.secrets:
            self._redactor.add(secret)
        self._agent_label = change.label
        if change.label != self._state.agent:
            await self._emit(AgentChanged(agent=change.label), actor_id=self._host.id)
        await self._sync_context(self._agent.fill())
        change.reply.set_result(None)

    async def _set_selection(self, participant_id: str, command: SelectionSet) -> None:
        if command.selection is None:
            if participant_id not in self._selecting:
                return
            self._selecting.discard(participant_id)
        else:
            self._selecting.add(participant_id)
        await self._emit(
            ParticipantSelected(participant_id=participant_id, selection=command.selection)
        )

    async def _set_cursor(self, participant_id: str, command: CursorSet) -> None:
        if command.cursor is None:
            if participant_id not in self._pointing:
                return
            self._pointing.discard(participant_id)
        else:
            self._pointing.add(participant_id)
        await self._emit(ParticipantCursor(participant_id=participant_id, cursor=command.cursor))

    async def _set_typing(self, participant_id: str, *, typing: bool) -> None:
        timer = self._typing.pop(participant_id, None)
        if timer is not None:
            timer.cancel()
        if typing:
            self._typing[participant_id] = asyncio.get_running_loop().call_later(
                self._typing_ttl_s, self._inbox.put, TypingExpired(participant_id)
            )
            if timer is None:
                await self._emit(ParticipantTyping(participant_id=participant_id, typing=True))
        elif timer is not None:
            await self._emit(ParticipantTyping(participant_id=participant_id, typing=False))

    async def _cancel_queued(self, participant: Participant, command: QueueCancel) -> None:
        entry = next(
            (queued for queued in self._state.queue if queued.prompt_id == command.prompt_id), None
        )
        if entry is None:
            raise NotFound(f"queued prompt {command.prompt_id}")
        if participant.role is not Role.HOST and entry.author_id != participant.id:
            raise Forbidden("only the author or the host can cancel a queued prompt")
        if not self._agent.cancel_pending(command.prompt_id):
            raise Conflict("the prompt has already reached the agent")
        await self._emit(
            PromptDequeued(prompt_id=command.prompt_id, reason=DequeueReason.CANCELLED),
            actor_id=participant.id,
        )

    async def _set_prompt_mode(self, mode: PromptMode, *, actor_id: str) -> None:
        if mode is not self._state.prompt_mode:
            await self._emit(PromptModeChanged(mode=mode), actor_id=actor_id)

    async def _set_permission_mode(self, mode: PermissionMode, *, actor_id: str) -> None:
        if mode is not self._state.permission_mode:
            await self._emit(PermissionModeChanged(mode=mode), actor_id=actor_id)

    def _library(self) -> SkillLibrary:
        if self._skills is None:
            raise Conflict("skills are not available on this host")
        return self._skills

    def _background(self, job: Coroutine[None, None, None]) -> None:
        task = asyncio.create_task(job)
        self._jobs.add(task)
        task.add_done_callback(self._jobs.discard)

    async def _search_skills(self, connection: Connection, query: str) -> None:
        try:
            hits = await self._library().search(query)
        except (SkillError, DomainError) as error:
            self._inbox.put(SkillsReply(connection, error=str(error)))
        else:
            self._inbox.put(SkillsReply(connection, SkillsFound(query=query, hits=hits)))

    async def _install_skill(
        self, connection: Connection, package: Package, scope: SkillScope
    ) -> None:
        try:
            await self._library().install(package, scope)
        except (SkillError, DomainError) as error:
            self._inbox.put(SkillsUpdated(connection, error=str(error)))
        except Exception:
            log.exception("actor.skill_install_failed", package=str(package))
            self._inbox.put(SkillsUpdated(connection, error=f"could not install {package}"))
        else:
            self._inbox.put(SkillsUpdated(connection))

    async def _mcp_command(
        self, command: McpAdd | McpRemove | McpToggle | McpRestart | McpImport, *, actor_id: str
    ) -> None:
        if self._mcp is None:
            raise Conflict("MCP is not available on this host")
        try:
            match command:
                case McpAdd():
                    if bool(command.command) == bool(command.url):
                        raise Invalid("give either a command to launch or a URL")
                    spec = ServerSpec(
                        command=command.command,
                        args=list(command.args),
                        url=command.url,
                        env=dict(command.env),
                        headers=dict(command.headers),
                    )
                    self._mcp.add(command.name, spec, command.scope)
                case McpRemove():
                    await self._mcp.remove(command.name)
                case McpToggle():
                    await self._mcp.toggle(command.name, enabled=command.enabled)
                case McpRestart():
                    await self._mcp.restart(command.name)
                case McpImport():
                    if not self._mcp.import_servers():
                        raise NotFound("no new MCP servers in Claude Code or Cursor settings")
        except McpError as error:
            raise Invalid(str(error)) from None
        for secret in self._mcp.secrets():
            self._redactor.add(secret)
        await self._sync_mcp(actor_id=actor_id)

    async def _sync_mcp(self, *, actor_id: str | None = None) -> None:
        if self._mcp is None:
            return
        servers = self._mcp.views()
        if servers != self._state.mcp:
            await self._emit(McpChanged(servers=servers), actor_id=actor_id or self._host.id)

    async def _sync_context(self, fill: agent.ContextFill) -> None:
        context = ContextView(tokens=fill.tokens, window=fill.window, compact_at=fill.compact_at)
        if context != self._state.context:
            await self._emit(ContextUsage(context=context))

    async def _sync_skills(self, *, actor_id: str | None = None) -> None:
        if self._skills is None:
            return
        views = self._skills.views()
        if views == self._state.skills:
            return
        before = {skill.name for skill in self._state.skills}
        after = {skill.name for skill in views}
        changed = SkillsChanged(
            skills=views, added=tuple(sorted(after - before)), removed=tuple(sorted(before - after))
        )
        await self._emit(changed, actor_id=actor_id or self._host.id)

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
        await self._set_typing(author.id, typing=False)
        body, images = await self._with_attachments(text, attachments)
        if self._state.permission_mode is PermissionMode.PLAN:
            body = f"{body}\n\n{PLAN_NOTE}"
        turn = UserTurn(
            id=prompt_id,
            author=Actor(id=author.id, kind=ActorKind.HUMAN, name=author.name),
            provenance=provenance,
            text=body,
            images=images,
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
            case agent.Delivered(prompt_ids=prompt_ids):
                for prompt_id in prompt_ids:
                    await self._emit(
                        PromptDequeued(prompt_id=prompt_id, reason=DequeueReason.DELIVERED)
                    )
            case agent.Compacting(tokens_before=tokens_before):
                await self._emit(ContextCompacting(run_id=run_id, tokens_before=tokens_before))
            case agent.ContextFill() as fill:
                await self._sync_context(fill)
            case agent.Compacted(summary=summary, tokens_before=tokens_before):
                await self._emit(
                    ContextCompacted(run_id=run_id, summary=summary, tokens_before=tokens_before)
                )
            case agent.ToolStart(call=call):
                await self._emit(ToolStarted(run_id=run_id, call=call))
            case agent.ToolOutput(call_id=call_id, chunk=chunk):
                await self._emit(ToolOutput(call_id=call_id, chunk=chunk))
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
        if reason is RunEndReason.ABORTED:
            for turn in pending:
                await self._emit(PromptDequeued(prompt_id=turn.id, reason=DequeueReason.DROPPED))
            return
        if not pending:
            return
        first, *rest = pending
        await self._emit(PromptDequeued(prompt_id=first.id, reason=DequeueReason.DELIVERED))
        await self._start_run(first)
        for turn in rest:
            self._agent.follow_up(turn)

    async def _on_disconnect(self, connection: Connection) -> None:
        knock = self._knocking.pop(connection.id, None)
        if knock is not None:
            knock.timer.cancel()
            if knock.request_id in self._state.join_requests:
                await self._emit(
                    joins.resolve(self._state, knock.request_id, JoinDecision.GONE, None)
                )
            return
        participant_id = self._publisher.unbind(connection)
        if participant_id is None or self._publisher.is_online(participant_id):
            return
        await self._set_typing(participant_id, typing=False)
        await self._set_selection(participant_id, SelectionSet(selection=None))
        await self._set_cursor(participant_id, CursorSet(cursor=None))
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
        limit = self._max_image_bytes if image_type(data) else self._max_attachment_bytes
        if len(data) > limit:
            raise Invalid(f"attachment exceeds {limit} bytes")
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

    async def _history(self, records: Sequence[EventRecord]) -> list[Message]:
        names = {pid: participant.name for pid, participant in self._state.participants.items()}
        texts: dict[str, str] = {}
        for record in records:
            event = record.event
            if isinstance(event, PromptAccepted) and event.attachments:
                try:
                    texts[event.prompt_id], _ = await self._with_attachments(
                        event.text, event.attachments, images=False
                    )
                except (KeyError, OSError):
                    log.warning("actor.attachment_missing", prompt_id=event.prompt_id)
        return history.replay(records, names=names, texts=texts)

    async def _with_attachments(
        self, text: str, attachment_ids: tuple[str, ...], *, images: bool = True
    ) -> tuple[str, tuple[LlmImage, ...]]:
        """The prompt with its text attachments inlined and its images apart.

        A replayed history keeps only a note of each image, so a restart does not resend them.
        """
        parts = [text]
        pictures: list[LlmImage] = []
        for attachment_id in attachment_ids:
            meta = self._state.attachments[attachment_id]
            data = await self._vault.read(attachment_id)
            if (media_type := image_type(data)) is None:
                body = data.decode(errors="replace")
                parts.append(f"[attachment {meta.name}, untrusted]\n{body}")
            elif images:
                parts.append(f"[image {meta.name}, untrusted, attached]")
                pictures.append(
                    LlmImage(media_type=media_type, data=base64.b64encode(data).decode())
                )
            else:
                parts.append(f"[image {meta.name}, no longer available]")
        return "\n\n".join(parts), tuple(pictures)

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
        if isinstance(event, PolicyRuleAdded | PolicyRuleRemoved | PermissionModeChanged):
            self._sync_policy()
        self._publisher.publish(record)

    def _sync_policy(self) -> None:
        self._gate.use_session_rules(policies.to_rules(self._state.policy))
        self._gate.use_mode(self._state.permission_mode)
