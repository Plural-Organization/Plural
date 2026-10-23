import asyncio
import os
from dataclasses import dataclass

from plural.agent.context import ContextBuilder
from plural.agent.loop import AgentLoop
from plural.agent.providers.base import LLMProvider
from plural.agent.providers.fake import DemoProvider
from plural.agent.sandbox.base import Workspace
from plural.agent.sandbox.local import LocalBackend
from plural.agent.tools.base import ToolCtx
from plural.agent.tools.registry import builtin_tools
from plural.core.policy.engine import Policy
from plural.host.actor import SessionActor
from plural.host.agent_run import AgentRun
from plural.host.approval_registry import ApprovalRegistry
from plural.host.attachments import AttachmentVault
from plural.host.config import HostSettings
from plural.host.gateway import Gateway
from plural.host.inbox import Inbox
from plural.host.invites import InviteBook
from plural.host.policy_gate import HostPolicyGate
from plural.host.publisher import Publisher
from plural.host.system import SystemClock, UlidGenerator
from plural.host.transport.base import HostTransport
from plural.host.transport.direct import DirectTransport
from plural.host.transport.relay_link import RelayLink
from plural.protocol.models import Participant, Role
from plural.security.keys import load_or_create_host_key
from plural.security.secrets import Redactor
from plural.security.tokens import TokenSigner
from plural.storage.sqlite_store import SqliteEventStore

HOST_PARTICIPANT_ID = "p_host"


class ConfigError(Exception):
    pass


@dataclass(slots=True)
class Host:
    room: str
    actor: SessionActor
    inbox: Inbox
    transport: HostTransport
    store: SqliteEventStore
    invites: InviteBook
    host_token: str
    host_link: str

    async def serve(self) -> None:
        async with asyncio.TaskGroup() as group:
            group.create_task(self.actor.run(), name="actor")
            group.create_task(self.transport.serve(self.inbox), name="transport")

    async def close(self) -> None:
        await self.store.close()


def build_provider(settings: HostSettings) -> LLMProvider:
    if settings.provider == "fake":
        return DemoProvider()
    raise ConfigError(f"provider {settings.provider!r} is not wired yet: pending provider spike")


async def build_host(settings: HostSettings, *, provider: LLMProvider | None = None) -> Host:
    ids, clock = UlidGenerator(), SystemClock()
    room = settings.room or ids.new("r_")
    state_dir = settings.state_dir
    signer = TokenSigner(await asyncio.to_thread(load_or_create_host_key, state_dir / "host_key"))
    store = await SqliteEventStore.open(state_dir / "sessions" / f"{room}.db")
    workspace = await asyncio.to_thread(Workspace.at, settings.workspace)
    inbox = Inbox()
    registry = ApprovalRegistry()
    gate = HostPolicyGate(
        policy=Policy(),
        registry=registry,
        inbox=inbox,
        ids=ids,
        clock=clock,
        timeout_s=settings.approval_timeout_s,
    )
    loop = AgentLoop(
        provider=provider or build_provider(settings),
        tools=builtin_tools(),
        gate=gate,
        context=ContextBuilder(project_notes=await _project_notes(workspace)),
        tool_ctx=ToolCtx(workspace=workspace, backend=LocalBackend()),
        ids=ids,
    )
    room_url = settings.room_url(room)
    invites = InviteBook(clock=clock, link_base=room_url)
    gateway = Gateway(
        room=room,
        signer=signer,
        invites=invites,
        ids=ids,
        clock=clock,
        token_ttl_s=settings.token_ttl_s,
    )
    host = Participant(id=HOST_PARTICIPANT_ID, name=settings.host_name, role=Role.HOST)
    api_key = settings.api_key.get_secret_value() if settings.api_key else None
    actor = SessionActor(
        inbox=inbox,
        store=store,
        publisher=Publisher(room=room, ids=ids, clock=clock),
        gateway=gateway,
        invites=invites,
        agent_run=AgentRun(loop, inbox),
        approval_registry=registry,
        vault=AttachmentVault(state_dir / "attachments" / room),
        redactor=Redactor.from_environment(os.environ, extra=[api_key] if api_key else []),
        ids=ids,
        clock=clock,
        host=host,
        max_attachment_bytes=settings.max_attachment_bytes,
    )
    await actor.start()
    transport: HostTransport = (
        RelayLink(url=settings.relay_url, room=room, signer=signer)
        if settings.relay_url
        else DirectTransport(host=settings.bind_host, port=settings.port)
    )
    host_token = gateway.issue(host)
    return Host(
        room=room,
        actor=actor,
        inbox=inbox,
        transport=transport,
        store=store,
        invites=invites,
        host_token=host_token,
        host_link=f"{room_url}?token={host_token}",
    )


async def _project_notes(workspace: Workspace) -> str | None:
    path = workspace.root / "AGENTS.md"
    try:
        return await asyncio.to_thread(path.read_text, encoding="utf-8")
    except FileNotFoundError:
        return None
