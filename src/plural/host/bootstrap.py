import asyncio
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from plural.agent.agents import AgentLibrary
from plural.agent.context import ContextBuilder, Environment
from plural.agent.loop import AgentLoop, LoopLimits
from plural.agent.mcp import BROWSER_SERVER, McpHub, browser_spec
from plural.agent.providers import anthropic_api
from plural.agent.providers.anthropic_oauth import AnthropicOAuthProvider
from plural.agent.providers.base import LLMProvider
from plural.agent.providers.web_search import (
    anthropic_oauth_search,
    anthropic_search,
    openai_search,
    web_search_tool,
)
from plural.agent.sandbox.base import Workspace
from plural.agent.sandbox.local import LocalBackend
from plural.agent.skills import SkillLibrary
from plural.agent.tools.agent import AgentTool
from plural.agent.tools.base import ToolCtx
from plural.agent.tools.board import board_tools
from plural.agent.tools.registry import builtin_tools
from plural.agent.tools.search import Searcher, WebSearchSlot
from plural.agent.tools.skills import skill_tools
from plural.core.policy.engine import Policy
from plural.host.actor import SessionActor
from plural.host.agent_run import AgentRun
from plural.host.approval_registry import ApprovalRegistry
from plural.host.attachments import AttachmentVault
from plural.host.board_desk import InboxDesk
from plural.host.briefing import BriefingService
from plural.host.config import HostSettings
from plural.host.conflicts import ConflictBoard
from plural.host.gateway import Gateway
from plural.host.inbox import Inbox, McpUpdated, SkillsUpdated
from plural.host.invites import InviteBook, RoomLink
from plural.host.ledger import ChangeLedger
from plural.host.policy_gate import HostPolicyGate
from plural.host.providers import (
    ConfigError,
    build_provider,
    provider_secrets,
    resolve_api_key,
)
from plural.host.publisher import Publisher
from plural.host.repo import git_branch
from plural.host.routing import build_helper
from plural.host.system import SystemClock, UlidGenerator
from plural.host.team import DirectoryClient, TeamStore
from plural.host.team_admission import TeamAdmission
from plural.host.transport.base import HostTransport
from plural.host.transport.direct import DirectTransport
from plural.host.transport.relay_link import RelayLink
from plural.protocol.models import HOST_PARTICIPANT_ID, Participant, Role
from plural.security.keys import load_or_create_host_key
from plural.security.secrets import Redactor
from plural.security.tokens import TokenSigner
from plural.storage.sqlite_store import SqliteEventStore


@dataclass(slots=True)
class Host:
    room: str
    actor: SessionActor
    inbox: Inbox
    transport: HostTransport
    store: SqliteEventStore
    agent_run: AgentRun
    invites: InviteBook
    room_link: RoomLink
    host_token: str
    host_link: str
    mcp: McpHub | None = None
    web_search: WebSearchSlot | None = None
    conflicts: ConflictBoard | None = None

    async def serve(self) -> None:
        async with asyncio.TaskGroup() as group:
            group.create_task(self.actor.run(), name="actor")
            group.create_task(self.transport.serve(self.inbox), name="transport")

    async def close(self) -> None:
        if self.mcp is not None:
            await self.mcp.close()
        await self.agent_run.close()
        await self.store.close()


def build_web_search(
    settings: HostSettings, api_key: str | None, provider: LLMProvider
) -> Searcher | None:
    """Search through the session provider's own search engine, when it has one."""
    if not settings.web_search or settings.base_url is not None:
        return None
    place = {
        "city": settings.web_search_city,
        "region": settings.web_search_region,
        "country": settings.web_search_country,
        "timezone": settings.web_search_timezone,
    }
    tool = web_search_tool(
        context_size=settings.web_search_context_size,
        max_uses=settings.web_search_max_uses,
        allowed_domains=settings.web_search_allowed_domains,
        blocked_domains=settings.web_search_blocked_domains,
        location={key: value for key, value in place.items() if value},
    )
    provider_name = settings.resolved_provider()
    family = "anthropic" if provider_name in {"anthropic", "anthropic_oauth"} else provider_name
    chosen, _, named = (settings.web_search_model or "").rpartition(":")
    model = named if chosen == family else settings.model
    match provider_name:
        case "anthropic" if api_key:
            return anthropic_search(model or anthropic_api.DEFAULT_MODEL, api_key, tool)
        case "anthropic_oauth" if isinstance(provider, AnthropicOAuthProvider):
            return anthropic_oauth_search(
                model or anthropic_api.DEFAULT_OAUTH_MODEL, provider.token, tool
            )
        case "openai" if api_key and model:
            return openai_search(model, api_key, tool)
        case _:
            return None


async def remember_session(
    store: SqliteEventStore, workspace: Path, settings: HostSettings, now: datetime
) -> None:
    await store.set_meta("workspace", str(workspace))
    await store.set_meta("host_name", settings.host_name)
    if await store.meta("created_at") is None:
        await store.set_meta("created_at", now.isoformat())
    if settings.title:
        await store.set_meta("title", settings.title)


async def build_host(settings: HostSettings, *, provider: LLMProvider | None = None) -> Host:
    api_key = resolve_api_key(settings, os.environ)
    ids, clock = UlidGenerator(), SystemClock()
    helper = build_helper(settings) if provider is None else None
    room = settings.room or ids.new("r_")
    state_dir = settings.state_dir
    signer = TokenSigner(await asyncio.to_thread(load_or_create_host_key, state_dir / "host_key"))
    store = await SqliteEventStore.open(state_dir / "sessions" / f"{room}.db")
    workspace = await asyncio.to_thread(Workspace.at, settings.workspace)
    await remember_session(store, workspace.root, settings, clock.now())
    inbox = Inbox()
    skills = SkillLibrary(project=workspace.root, home=Path.home())
    tools = builtin_tools()
    agent = provider or build_provider(settings, api_key)
    web_search = WebSearchSlot()
    web_search.use(build_web_search(settings, api_key, agent))
    tools.add_source(web_search)
    for tool in skill_tools(skills, lambda: inbox.put(SkillsUpdated())):
        tools.register(tool)
    mcp = McpHub(
        workspace=workspace.root,
        home=Path.home(),
        logs=state_dir / "logs",
        on_change=lambda: inbox.put(McpUpdated()),
        builtin=(
            {BROWSER_SERVER: browser_spec(settings.browser, state_dir / "browser")}
            if settings.browser not in {"", "off"}
            else None
        ),
    )
    tools.add_source(mcp)
    mcp.start()
    registry = ApprovalRegistry()
    gate = HostPolicyGate(
        policy=Policy(),
        registry=registry,
        inbox=inbox,
        ids=ids,
        clock=clock,
        timeout_s=settings.approval_timeout_s,
        rejection_limit=settings.rejection_limit,
    )
    environment = Environment(
        workspace=workspace.root,
        today=clock.now().astimezone().date(),
        git_branch=await git_branch(workspace.root),
    )
    agents = AgentLibrary(project=workspace.root, home=Path.home())
    await asyncio.to_thread(agents.refresh)
    delegate = AgentTool(library=agents, tools=tools, gate=gate, environment=environment, ids=ids)
    tools.register(delegate)
    desk = InboxDesk(inbox)
    for tool in board_tools(desk):
        tools.register(tool)
    loop = AgentLoop(
        provider=agent,
        helper=helper.provider if helper else None,
        tools=tools,
        gate=gate,
        context=ContextBuilder(
            environment=environment,
            project_notes=await _project_notes(workspace),
            skills=skills,
            agents=agents,
        ),
        tool_ctx=ToolCtx(workspace=workspace, backend=LocalBackend()),
        ids=ids,
        limits=LoopLimits(
            first_token_timeout_s=settings.first_token_timeout_s,
            idle_timeout_s=settings.idle_timeout_s,
            context_window=settings.context_window,
            compact_at=settings.compact_at,
        ),
    )
    delegate.attach(lambda: loop)
    room_url = settings.room_url(room)
    invites = InviteBook(clock=clock, link_base=room_url)
    link_code = await store.meta("room_link")
    if link_code is None:
        link_code = secrets.token_urlsafe(18)
        await store.set_meta("room_link", link_code)
    room_link = RoomLink(code=link_code, link_base=room_url)
    gateway = Gateway(
        room=room,
        signer=signer,
        invites=invites,
        link=room_link,
        ids=ids,
        clock=clock,
        token_ttl_s=settings.token_ttl_s,
    )
    host = Participant(id=HOST_PARTICIPANT_ID, name=settings.host_name, role=Role.HOST)
    team = await _team_admission(settings, store, clock, room) if settings.team else None
    board = ConflictBoard(workspace.root) if settings.team else None
    agent_run = AgentRun(loop, inbox)
    redactor = Redactor.from_environment(
        os.environ,
        extra=(
            *provider_secrets(settings, api_key),
            *(helper.secrets if helper else ()),
            *mcp.secrets(),
        ),
    )
    ledger = ChangeLedger(workspace.root)
    briefing = BriefingService(
        agent=agent_run,
        ledger=ledger,
        workspace=workspace.root,
        owner=settings.host_name,
        scrub=redactor.redact,
    )
    actor = SessionActor(
        inbox=inbox,
        store=store,
        publisher=Publisher(room=room, ids=ids, clock=clock),
        gateway=gateway,
        invites=invites,
        link=room_link,
        agent_run=agent_run,
        approval_registry=registry,
        gate=gate,
        vault=AttachmentVault(state_dir / "attachments" / room),
        redactor=redactor,
        ids=ids,
        clock=clock,
        host=host,
        max_attachment_bytes=settings.max_attachment_bytes,
        max_image_bytes=settings.max_image_bytes,
        prompt_mode=settings.prompt_mode,
        admission=settings.admission,
        skills=skills,
        mcp=mcp,
        agents=agents,
        typing_ttl_s=settings.typing_ttl_s,
        agent_label=settings.agent_label(),
        fast_label=helper.label if helper else "",
        join_timeout_s=settings.join_timeout_s,
        max_pending_joins=settings.max_pending_joins,
        max_participants=settings.max_participants,
        team=team,
        conflicts=board,
        briefing=briefing,
        ledger=ledger,
        team_sweep_s=settings.team_roster_ttl_s,
    )
    desk.attach(actor.board)
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
        agent_run=agent_run,
        invites=invites,
        room_link=room_link,
        host_token=host_token,
        host_link=f"{room_url}?token={host_token}",
        mcp=mcp,
        web_search=web_search,
        conflicts=board,
    )


async def _team_admission(
    settings: HostSettings, store: SqliteEventStore, clock: SystemClock, room: str
) -> TeamAdmission:
    team_store = TeamStore(settings.state_dir)
    profile = await asyncio.to_thread(team_store.load)
    if profile is None:
        raise ConfigError("this session is for a team, but you are not in one")
    directory = DirectoryClient(team_store, profile)
    banned: list[str] = []
    try:
        stored: object = json.loads(await store.meta("team_banned") or "[]")
    except ValueError:
        stored = None
    if isinstance(stored, list):
        banned = [str(entry) for entry in cast("list[object]", stored) if isinstance(entry, str)]
    return TeamAdmission(
        team_id=profile.team_id,
        team_key=profile.team_key,
        members=directory.members,
        urls=(settings.room_url(room),),
        clock=clock,
        banned=banned,
        roster_ttl_s=settings.team_roster_ttl_s,
    )


async def _project_notes(workspace: Workspace) -> str | None:
    path = workspace.root / "AGENTS.md"
    try:
        return await asyncio.to_thread(path.read_text, encoding="utf-8")
    except FileNotFoundError:
        return None
