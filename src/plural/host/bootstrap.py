import asyncio
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from plural.agent.context import ContextBuilder, Environment
from plural.agent.loop import AgentLoop, LoopLimits
from plural.agent.mcp import BROWSER_SERVER, McpHub, browser_spec
from plural.agent.providers import anthropic_api
from plural.agent.providers.anthropic_api import AnthropicProvider
from plural.agent.providers.anthropic_oauth import AnthropicOAuthProvider, load_credentials
from plural.agent.providers.base import LLMProvider
from plural.agent.providers.claude_code import ClaudeCodeProvider
from plural.agent.providers.codex_cli import CodexCliProvider
from plural.agent.providers.fake import DemoProvider
from plural.agent.providers.openai_compat import OpenAIProvider
from plural.agent.sandbox.base import Workspace
from plural.agent.sandbox.local import LocalBackend
from plural.agent.skills import SkillLibrary
from plural.agent.tools.base import ToolCtx
from plural.agent.tools.registry import builtin_tools
from plural.agent.tools.skills import skill_tools
from plural.core.policy.engine import Policy
from plural.host.actor import SessionActor
from plural.host.agent_run import AgentRun
from plural.host.approval_registry import ApprovalRegistry
from plural.host.attachments import AttachmentVault
from plural.host.config import HostSettings
from plural.host.gateway import Gateway
from plural.host.inbox import Inbox, McpUpdated, SkillsUpdated
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
KEY_VARIABLES = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
LOCAL_SERVER_KEY = "not-needed"


class ConfigError(Exception):
    pass


@dataclass(slots=True)
class Host:
    room: str
    actor: SessionActor
    inbox: Inbox
    transport: HostTransport
    store: SqliteEventStore
    agent_run: AgentRun
    invites: InviteBook
    host_token: str
    host_link: str
    mcp: McpHub | None = None

    async def serve(self) -> None:
        async with asyncio.TaskGroup() as group:
            group.create_task(self.actor.run(), name="actor")
            group.create_task(self.transport.serve(self.inbox), name="transport")

    async def close(self) -> None:
        if self.mcp is not None:
            await self.mcp.close()
        await self.agent_run.close()
        await self.store.close()


def resolve_api_key(settings: HostSettings, environ: Mapping[str, str]) -> str | None:
    if settings.api_key is not None:
        return settings.api_key.get_secret_value()
    variable = KEY_VARIABLES.get(settings.resolved_provider(environ))
    return environ.get(variable) if variable else None


def provider_secrets(settings: HostSettings, api_key: str | None) -> tuple[str, ...]:
    if settings.resolved_provider() == "anthropic_oauth":
        credentials = load_credentials(settings.state_dir / "anthropic-oauth.json")
        return (credentials.access, credentials.refresh)
    return (api_key,) if api_key else ()


def build_provider(settings: HostSettings, api_key: str | None) -> LLMProvider:
    match settings.resolved_provider():
        case "fake":
            return DemoProvider()
        case "anthropic":
            if not api_key:
                raise ConfigError(
                    "set PLURAL_API_KEY or ANTHROPIC_API_KEY for the anthropic provider"
                )
            return AnthropicProvider(
                api_key=api_key,
                model=settings.model or anthropic_api.DEFAULT_MODEL,
                max_tokens=settings.max_output_tokens or anthropic_api.DEFAULT_MAX_TOKENS,
                effort=settings.effort,
                base_url=settings.base_url,
            )
        case "anthropic_oauth":
            return AnthropicOAuthProvider(
                credentials_path=settings.state_dir / "anthropic-oauth.json",
                model=settings.model or anthropic_api.DEFAULT_OAUTH_MODEL,
                max_tokens=settings.max_output_tokens or anthropic_api.DEFAULT_MAX_TOKENS,
                effort=settings.effort,
            )
        case "claude_code":
            return ClaudeCodeProvider(
                workspace=settings.workspace,
                model=settings.model or "claude-sonnet-5-5",
            )
        case "codex_cli":
            return CodexCliProvider(
                workspace=settings.workspace,
                model=settings.model or CodexCliProvider.DEFAULT_MODEL,
            )
        case "openai":
            if not settings.model:
                raise ConfigError("set PLURAL_MODEL for the openai provider")
            if not api_key and settings.base_url is None:
                raise ConfigError("set PLURAL_API_KEY or OPENAI_API_KEY for the openai provider")
            return OpenAIProvider(
                api_key=api_key or LOCAL_SERVER_KEY,
                model=settings.model,
                base_url=settings.base_url,
                max_tokens=settings.max_output_tokens,
                effort=settings.effort,
            )


async def build_host(settings: HostSettings, *, provider: LLMProvider | None = None) -> Host:
    api_key = resolve_api_key(settings, os.environ)
    ids, clock = UlidGenerator(), SystemClock()
    room = settings.room or ids.new("r_")
    state_dir = settings.state_dir
    signer = TokenSigner(await asyncio.to_thread(load_or_create_host_key, state_dir / "host_key"))
    store = await SqliteEventStore.open(state_dir / "sessions" / f"{room}.db")
    workspace = await asyncio.to_thread(Workspace.at, settings.workspace)
    inbox = Inbox()
    skills = SkillLibrary(project=workspace.root, home=Path.home())
    tools = builtin_tools()
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
    loop = AgentLoop(
        provider=provider or build_provider(settings, api_key),
        tools=tools,
        gate=gate,
        context=ContextBuilder(
            environment=Environment(
                workspace=workspace.root,
                today=clock.now().astimezone().date(),
                git_branch=await _git_branch(workspace),
            ),
            project_notes=await _project_notes(workspace),
            skills=skills,
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
    agent_run = AgentRun(loop, inbox)
    actor = SessionActor(
        inbox=inbox,
        store=store,
        publisher=Publisher(room=room, ids=ids, clock=clock),
        gateway=gateway,
        invites=invites,
        agent_run=agent_run,
        approval_registry=registry,
        gate=gate,
        vault=AttachmentVault(state_dir / "attachments" / room),
        redactor=Redactor.from_environment(
            os.environ, extra=(*provider_secrets(settings, api_key), *mcp.secrets())
        ),
        ids=ids,
        clock=clock,
        host=host,
        max_attachment_bytes=settings.max_attachment_bytes,
        prompt_mode=settings.prompt_mode,
        skills=skills,
        mcp=mcp,
        typing_ttl_s=settings.typing_ttl_s,
        agent_label=settings.agent_label(),
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
        agent_run=agent_run,
        invites=invites,
        host_token=host_token,
        host_link=f"{room_url}?token={host_token}",
        mcp=mcp,
    )


async def _git_branch(workspace: Workspace) -> str | None:
    try:
        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(workspace.root),
            "rev-parse",
            "--abbrev-ref",
            "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return None
    try:
        output, _ = await asyncio.wait_for(process.communicate(), 5)
    except TimeoutError:
        process.kill()
        await process.wait()
        return None
    branch = output.decode(errors="replace").strip()
    if process.returncode != 0 or not branch:
        return None
    return "detached HEAD" if branch == "HEAD" else branch


async def _project_notes(workspace: Workspace) -> str | None:
    path = workspace.root / "AGENTS.md"
    try:
        return await asyncio.to_thread(path.read_text, encoding="utf-8")
    except FileNotFoundError:
        return None
