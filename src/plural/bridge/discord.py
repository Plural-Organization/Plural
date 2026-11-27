"""Discord: the gateway in, the REST API out.

The bot hears messages through the gateway (a websocket), so it needs no public address. Replies
are ordinary messages that are edited as the run goes, with buttons under approvals. Slash commands
and buttons arrive as interactions, which Discord wants answered within three seconds, so each is
acknowledged at once and the real reply comes as a message.

The bot token is a secret: it never appears in a log line or an error.
"""

import asyncio
import json
import random
import re
import urllib.error
import urllib.request
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Final, Protocol, cast

import structlog
import websockets

from plural.bridge.live import LiveMessages, Slot
from plural.bridge.model import (
    Answer,
    Incoming,
    Notice,
    Person,
    Phase,
    Place,
    Pressed,
    Said,
    StepState,
    Tone,
)
from plural.bridge.platform import AuthError, Links, PlatformError

log = structlog.get_logger(__name__)

API: Final = "https://discord.com/api/v10"
PLATFORM: Final = "discord"
EDIT_EVERY_S: Final = 2.0
TYPING_EVERY_S: Final = 8.0
MAX_MESSAGE: Final = 2000
LIVE_TAIL: Final = 1800
MAX_STEPS: Final = 6
DEFAULT_NAMES: Final = ("plural", "плюрал", "плурал")
# Guilds, guild messages, direct messages and the content of messages (a privileged intent that
# the person turns on for the bot in the Developer Portal).
INTENTS: Final = 1 | (1 << 9) | (1 << 12) | (1 << 15)
STYLE: Final = {Tone.PRIMARY: 1, Tone.PLAIN: 2, Tone.GOOD: 3, Tone.DANGER: 4}
ICON: Final = {StepState.RUNNING: "⏳", StepState.OK: "✓", StepState.FAILED: "✗"}
EPHEMERAL: Final = 64
# View channels, send messages, embed links, read history, and send in threads: all the bot does.
INVITE_PERMISSIONS: Final = (1 << 10) | (1 << 11) | (1 << 14) | (1 << 16) | (1 << 38)
COMMANDS: Final = (
    ("link", "Pick the session this chat follows", None),
    ("unlink", "Stop following the session here", None),
    ("status", "Which session this chat follows", None),
    ("stop", "Stop the agent's current run", None),
    ("mute", "Stop alerts about sessions this chat does not follow", None),
    ("unmute", "Alert me when a session needs me or finishes", None),
    ("ask", "Send a prompt to the agent", "What to ask"),
    ("help", "What the bot does", None),
    ("pair", "Become the bot's owner", "The code from Plural's settings"),
)
_MENTION = re.compile(r"<@!?(\d+)>")


class DiscordError(PlatformError):
    def __init__(self, description: str, code: int = 0, retry_after: float | None = None) -> None:
        super().__init__(description)
        self.code = code
        self.retry_after = retry_after


class DiscordApi:
    """The REST API over HTTPS, one call at a time in a worker thread."""

    def __init__(self, token: str, *, base: str = API) -> None:
        self.token = token
        self._base = base

    async def call(self, method: str, path: str, body: Any = None, *, wait_s: float = 20) -> Any:
        data = None if body is None else json.dumps(body).encode()
        return await asyncio.to_thread(self._request, method, path, data, wait_s)

    def _request(self, method: str, path: str, data: bytes | None, timeout: float) -> Any:
        # An interaction's own token is its credential; the bot token goes everywhere else.
        headers = {"Content-Type": "application/json", "User-Agent": "DiscordBot (plural, 1)"}
        if not path.startswith(("/interactions/", "/webhooks/")):
            headers["Authorization"] = f"Bot {self.token}"
        request = urllib.request.Request(
            self._base + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            reply: dict[str, Any]
            try:
                reply = _obj(json.load(error))
            except ValueError:
                reply = {}
            text = str(reply.get("message") or f"HTTP {error.code}")
            if error.code == 401:
                raise AuthError("Discord does not accept this token") from None
            wait = reply.get("retry_after")
            raise DiscordError(
                text, error.code, float(wait) if isinstance(wait, int | float) else None
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise DiscordError(f"network: {getattr(error, 'reason', error)}") from None
        return json.loads(raw) if raw else None


class Gateway(Protocol):
    def events(self) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Dispatch events as (name, data), kept connected across drops."""
        ...


class WebsocketGateway:
    """The gateway connection: heartbeat, identify, resume and reconnect."""

    def __init__(self, token: str, url: str, *, intents: int = INTENTS) -> None:
        self._token = token
        self._url = url
        self._intents = intents
        self._session: str | None = None
        self._resume_url: str | None = None
        self._seq: int | None = None

    async def events(self) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        delay = 1.0
        while True:
            try:
                url = (self._resume_url or self._url) + "?v=10&encoding=json"
                async with websockets.connect(url, max_size=None) as socket:
                    delay = 1.0
                    async for name, data in self._session_events(socket):
                        yield name, data
            except websockets.ConnectionClosed as closed:
                code = closed.rcvd.code if closed.rcvd else 0
                if code == 4004:
                    raise AuthError("Discord does not accept this token") from None
                if code in (4013, 4014):
                    raise PlatformError(
                        "Discord refused the intents: turn on Message Content Intent "
                        "for the bot in the Developer Portal"
                    ) from None
                if code in (4007, 4009):
                    self._session = None
                log.info("discord.gateway_closed", code=code)
            except (OSError, websockets.WebSocketException) as error:
                log.warning("discord.gateway_failed", error=type(error).__name__)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)

    async def _session_events(self, socket: Any) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        beat: asyncio.Task[None] | None = None
        acked = True
        try:
            async for raw in socket:
                message = json.loads(raw)
                op, data = message["op"], message.get("d")
                if message.get("s") is not None:
                    self._seq = int(message["s"])
                if op == 10:
                    interval = data["heartbeat_interval"] / 1000

                    async def heartbeat(every: float = interval) -> None:
                        nonlocal acked
                        await asyncio.sleep(every * random.random())
                        while True:
                            if not acked:
                                await socket.close(4000)
                                return
                            acked = False
                            await socket.send(json.dumps({"op": 1, "d": self._seq}))
                            await asyncio.sleep(every)

                    beat = asyncio.create_task(heartbeat())
                    await socket.send(json.dumps(self._hello()))
                elif op == 11:
                    acked = True
                elif op == 1:
                    await socket.send(json.dumps({"op": 1, "d": self._seq}))
                elif op in (7, 9):
                    if op == 9 and not data:
                        self._session = None
                    await socket.close(4000)
                    return
                elif op == 0:
                    name = str(message["t"])
                    if name == "READY":
                        self._session = str(data["session_id"])
                        self._resume_url = str(data["resume_gateway_url"])
                    yield name, cast(dict[str, Any], data)
        finally:
            if beat is not None:
                beat.cancel()
                with suppress(asyncio.CancelledError):
                    await beat

    def _hello(self) -> dict[str, Any]:
        if self._session is not None:
            return {
                "op": 6,
                "d": {"token": self._token, "session_id": self._session, "seq": self._seq},
            }
        return {
            "op": 2,
            "d": {
                "token": self._token,
                "intents": self._intents,
                "properties": {"os": "any", "browser": "plural", "device": "plural"},
            },
        }


@dataclass(slots=True)
class _Tick:
    typing_at: float = 0.0


class Discord:
    name = PLATFORM

    def __init__(
        self,
        api: DiscordApi,
        *,
        names: Sequence[str] = DEFAULT_NAMES,
        gateway: Callable[[str], Gateway] | None = None,
    ) -> None:
        self._api = api
        self._token_gateway = gateway
        self._gateway: Gateway | None = None
        self.names = [name.strip().lower() for name in names if name.strip()]
        self._me_id = ""
        self._app_id = ""
        self.username = ""
        self._live = LiveMessages(
            self._put,
            every=lambda _place, _view: EDIT_EVERY_S,
            retry_after=_retry_after,
        )
        self._typed_at: dict[str, float] = {}
        self._cleanup: list[asyncio.Task[None]] = []

    @property
    def identity(self) -> str:
        return f"@{self.username}" if self.username else ""

    @property
    def links(self) -> Links:
        if not self._app_id:
            return Links()
        return Links(
            open=f"https://discord.com/users/{self._me_id}",
            invite=f"https://discord.com/oauth2/authorize?client_id={self._app_id}"
            f"&scope=bot%20applications.commands&permissions={INVITE_PERMISSIONS}",
        )

    async def start(self) -> None:
        if self._me_id:
            return
        me = await self._api.call("GET", "/users/@me")
        self._me_id = str(me["id"])
        self.username = str(me.get("global_name") or me.get("username") or "")
        first = self.username.strip().lower()
        if first and first not in self.names:
            self.names.append(first)
        app = await self._api.call("GET", "/oauth2/applications/@me")
        self._app_id = str(app["id"])
        try:
            await self._api.call("PUT", f"/applications/{self._app_id}/commands", _commands())
        except DiscordError as error:
            log.warning("discord.commands_failed", error=str(error))
        found = await self._api.call("GET", "/gateway")
        url = str(found["url"])
        self._gateway = (
            self._token_gateway(url)
            if self._token_gateway
            else WebsocketGateway(self._api.token, url)
        )

    async def incoming(self) -> AsyncIterator[Incoming]:
        if self._gateway is None:
            raise PlatformError("Discord is not started")
        async for name, data in self._gateway.events():
            item: Incoming | None = None
            if name == "MESSAGE_CREATE":
                item = self.parse_message(data)
            elif name == "INTERACTION_CREATE":
                item = await self._interaction(data)
            if item is not None:
                yield item

    def parse_message(self, message: dict[str, Any]) -> Said | None:
        author = _obj(message.get("author"))
        if not author or author.get("bot") or str(author.get("id")) == self._me_id:
            return None
        text = str(message.get("content") or "")
        if not text.strip():
            return None
        private = message.get("guild_id") is None
        addressed = private
        users = cast(list[object], message.get("mentions") or [])
        mentioned = any(str(_obj(user).get("id")) == self._me_id for user in users)
        if mentioned:
            addressed = True
            text = _MENTION.sub(
                lambda found: "" if found.group(1) == self._me_id else found.group(0), text
            ).strip()
        elif (rest := _called(text, self.names)) is not None:
            addressed = True
            text = rest
        replied = _obj(message.get("referenced_message"))
        if str(_obj(replied.get("author")).get("id")) == self._me_id:
            addressed = True
        return Said(
            place=_place(message, private),
            person=_person(author),
            text=text,
            addressed=addressed,
            ref=str(message["id"]),
        )

    async def _interaction(self, data: dict[str, Any]) -> Incoming | None:
        member = _obj(data.get("member"))
        who = _obj(member.get("user")) or _obj(data.get("user"))
        if not who:
            return None
        private = data.get("guild_id") is None
        place = Place(PLATFORM, str(data.get("channel_id", "")), None, private)
        token = f"{data['id']}/{data['token']}"
        kind = data.get("type")
        if kind == 2:
            await self._ack(token, 5, ephemeral=True)
            self._cleanup.append(asyncio.create_task(self._forget_reply(str(data["token"]))))
            self._cleanup = [task for task in self._cleanup if not task.done()]
            body = _obj(data.get("data"))
            options = cast(list[object], body.get("options") or [])
            rest = " ".join(str(_obj(option).get("value", "")) for option in options)
            return Said(
                place=place,
                person=_person(who),
                text=f"/{body.get('name', '')} {rest}".strip(),
                addressed=True,
            )
        if kind == 3:
            await self._ack(token, 6)
            return Pressed(
                place=place,
                person=_person(who),
                data=str(_obj(data.get("data")).get("custom_id", "")),
                query=str(data["token"]),
            )
        return None

    async def _ack(self, token: str, kind: int, *, ephemeral: bool = False) -> None:
        body: dict[str, Any] = {"type": kind}
        if ephemeral:
            body["data"] = {"flags": EPHEMERAL}
        try:
            await self._api.call("POST", f"/interactions/{token}/callback", body)
        except DiscordError as error:
            log.info("discord.ack_failed", error=str(error))

    async def _forget_reply(self, token: str) -> None:
        """A slash command's own "thinking" reply is not wanted: the bot answers as a message."""
        with suppress(PlatformError):
            await self._api.call("DELETE", f"/webhooks/{self._app_id}/{token}/messages/@original")

    async def show(
        self,
        place: Place,
        key: str,
        view: Answer | Notice,
        *,
        final: bool = True,
        reply_to: str | None = None,
    ) -> None:
        await self._live.show(place, key, view, final=final, reply_to=reply_to)

    async def _put(
        self, place: Place, slot: Slot, view: Answer | Notice, final: bool, reply_to: str | None
    ) -> None:
        components = _components(view)
        parts = split(render(view)) if final else [clip(render(view))]
        first, rest = parts[0], parts[1:]
        signature = first + json.dumps(components)
        if slot.message_id is None:
            sent = await self._api.call(
                "POST",
                f"/channels/{place.chat}/messages",
                _message(first, components if not rest else [], reply_to),
            )
            slot.message_id = str(sent["id"])
        elif signature != slot.sent:
            await self._api.call(
                "PATCH",
                f"/channels/{place.chat}/messages/{slot.message_id}",
                {"content": first, "components": components if not rest else []},
            )
        slot.sent = signature
        for index, part in enumerate(rest):
            last = index == len(rest) - 1
            await self._api.call(
                "POST",
                f"/channels/{place.chat}/messages",
                _message(part, components if last else [], None),
            )
        if not final:
            await self._typing(place)

    async def _typing(self, place: Place) -> None:
        loop = asyncio.get_running_loop()
        if loop.time() - self._typed_at.get(place.chat, -TYPING_EVERY_S) < TYPING_EVERY_S:
            return
        self._typed_at[place.chat] = loop.time()
        with suppress(PlatformError):
            await self._api.call("POST", f"/channels/{place.chat}/typing")

    async def answer(self, pressed: Pressed, text: str = "", *, alert: bool = False) -> None:
        """The button was acknowledged when it arrived; words for the person who pressed it go
        out as a follow-up only they can see."""
        if pressed.query is None or not text:
            return
        with suppress(PlatformError):
            await self._api.call(
                "POST",
                f"/webhooks/{self._app_id}/{pressed.query}",
                {"content": text[:1900], "flags": EPHEMERAL},
            )

    async def close(self) -> None:
        await self._live.close()


def _retry_after(error: PlatformError) -> float | None:
    return error.retry_after if isinstance(error, DiscordError) else None


def render(view: Answer | Notice) -> str:
    """Discord Markdown for a view. Text from the agent is Markdown already and goes as it is."""
    if isinstance(view, Notice):
        return view.text
    parts: list[str] = []
    if view.asked_by and view.question:
        question = " ".join(view.question.split())
        if len(question) > 200:
            question = question[:199] + "…"
        parts.append(f"> **{_plain(view.asked_by)}:** {_plain(question)}")
    if view.steps:
        parts.append(_steps(view))
    if view.text.strip():
        parts.append(view.text.strip())
    elif not view.finished:
        parts.append("*Thinking…*")
    match view.phase:
        case Phase.STOPPED:
            parts.append("*⏹ Stopped.*")
        case Phase.FAILED:
            reason = f": {_plain(view.error)}" if view.error else ""
            parts.append(f"⚠️ **The run failed**{reason}")
        case Phase.DONE if not view.text.strip():
            parts.append("*Done.*")
        case _:
            pass
    return "\n\n".join(parts)


def _steps(view: Answer) -> str:
    running = any(step.state is StepState.RUNNING for step in view.steps)
    count = len(view.steps)
    lines = [f"🛠 **{count} step{'s' if count != 1 else ''}**" + (" · working" if running else "")]
    shown = view.steps[-MAX_STEPS:]
    if count > len(shown):
        lines.append(f"-# … {count - len(shown)} earlier")
    for step in shown:
        subject = " ".join(step.subject.split())
        if len(subject) > 70:
            subject = subject[:69] + "…"
        tail = f" `{subject.replace('`', "'")}`" if subject else ""
        lines.append(f"-# {ICON[step.state]} `{step.tool}`{tail}")
    return "\n".join(lines)


def _plain(text: str) -> str:
    return re.sub(r"([\\*_~`|>])", r"\\\1", text)


def _components(view: Answer | Notice) -> list[dict[str, Any]]:
    if isinstance(view, Answer):
        if view.finished:
            return []
        stop = {"type": 2, "style": 4, "label": "⏹ Stop", "custom_id": "stop"}
        return [{"type": 1, "components": [stop]}]
    return [
        {
            "type": 1,
            "components": [
                {
                    "type": 2,
                    "style": STYLE[choice.tone],
                    "label": choice.label[:80],
                    "custom_id": choice.data[:100],
                }
                for choice in row[:5]
            ],
        }
        for row in view.choices[:5]
    ]


def _message(
    content: str, components: list[dict[str, Any]], reply_to: str | None
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "content": content,
        "components": components,
        # Nothing the agent writes may ping anyone.
        "allowed_mentions": {"parse": []},
    }
    if reply_to:
        body["message_reference"] = {"message_id": reply_to, "fail_if_not_exists": False}
    return body


def clip(markdown: str) -> str:
    """A live view shows the end of a long answer: that is what changes."""
    if len(markdown) <= LIVE_TAIL:
        return markdown
    return "…" + markdown[-(LIVE_TAIL - 1) :]


def split(markdown: str) -> list[str]:
    """Pieces under Discord's limit, cut between paragraphs where it can."""
    # A piece of cut code is reopened and closed again, and those fences count too.
    limit = MAX_MESSAGE - len("```\n\n```") if "```" in markdown else MAX_MESSAGE
    parts: list[str] = []
    rest = markdown
    while len(rest) > limit:
        cut = rest.rfind("\n\n", 0, limit)
        if cut < limit // 2:
            cut = rest.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    parts.append(rest)
    return _keep_fences(parts)


def _keep_fences(parts: list[str]) -> list[str]:
    """A code block cut in two is closed in the first piece and reopened in the next."""
    out: list[str] = []
    open_fence = False
    for part in parts:
        text = ("```\n" if open_fence else "") + part
        open_fence = text.count("```") % 2 == 1
        out.append(text + ("\n```" if open_fence else ""))
    return out


def _commands() -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = []
    for name, description, option in COMMANDS:
        entry: dict[str, Any] = {"name": name, "description": description, "type": 1}
        if option:
            entry["options"] = [
                {
                    "type": 3,
                    "name": "text",
                    "description": option,
                    "required": True,
                }
            ]
        commands.append(entry)
    return commands


def _place(message: dict[str, Any], private: bool) -> Place:
    return Place(PLATFORM, str(message["channel_id"]), None, private)


def _person(user: dict[str, Any]) -> Person:
    name = user.get("global_name") or user.get("username") or str(user["id"])
    return Person(id=str(user["id"]), name=str(name))


def _obj(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _called(text: str, names: Sequence[str]) -> str | None:
    lowered = text.lower()
    for name in sorted(names, key=len, reverse=True):
        if lowered.startswith(name) and (len(text) == len(name) or not text[len(name)].isalnum()):
            return text[len(name) :].lstrip(" ,:;!-—–").strip()
    return None
