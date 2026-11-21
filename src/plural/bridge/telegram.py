"""Telegram through the Bot API: long polling in, rich messages out.

Replies are rich messages (Bot API 10.1), whose Markdown is close to what agents write. In a
private chat a reply streams as a draft with Telegram's own "Thinking…" placeholder and stop
button, and becomes a message when the run ends. A group has no drafts, so there the bot sends a
message at once and edits it as the run goes, at most every couple of seconds. An approval is a
message with buttons, edited when it is answered.

The bot token is a secret: it is part of every request's address, so neither the address nor a
request is ever logged.
"""

import asyncio
import hashlib
import json
import re
import urllib.error
import urllib.request
from collections.abc import AsyncIterator, Sequence
from typing import Any, Final, cast

import structlog

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
from plural.bridge.platform import AuthError, PlatformError

log = structlog.get_logger(__name__)

API: Final = "https://api.telegram.org"
PLATFORM: Final = "telegram"
POLL_S: Final = 25
EDIT_EVERY_S: Final = 2.0
DRAFT_EVERY_S: Final = 1.0
MAX_RICH: Final = 30_000
MAX_PLAIN: Final = 4_000
MAX_STEPS: Final = 25
STYLE: Final = {Tone.GOOD: "success", Tone.DANGER: "danger", Tone.PRIMARY: "primary"}
ICON: Final = {StepState.RUNNING: "⏳", StepState.OK: "✓", StepState.FAILED: "✗"}
_ESCAPED = re.compile(r"([\\`*_~|=\[\]<>#])")
# A message that starts with one of these, like "plural, what does this do?", is for the bot.
DEFAULT_NAMES: Final = ("plural", "плюрал", "плурал")
COMMANDS: Final = (
    ("link", "Pick the session this chat follows"),
    ("unlink", "Stop following the session here"),
    ("status", "Which session this chat follows"),
    ("stop", "Stop the agent's current run"),
    ("ask", "Send a prompt without a mention"),
    ("help", "What the bot does"),
)


class TelegramError(PlatformError):
    def __init__(self, description: str, code: int = 0, retry_after: float | None = None) -> None:
        super().__init__(description)
        self.code = code
        self.retry_after = retry_after


class TelegramApi:
    """The Bot API over HTTPS, one call at a time in a worker thread."""

    def __init__(self, token: str, *, base: str = API) -> None:
        self._url = f"{base}/bot{token}/"

    async def call(self, method: str, *, wait_s: float = 30, **params: Any) -> Any:
        body = json.dumps({key: value for key, value in params.items() if value is not None})
        return await asyncio.to_thread(self._post, method, body.encode(), wait_s)

    def _post(self, method: str, body: bytes, timeout: float) -> Any:
        request = urllib.request.Request(
            self._url + method, data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                reply = json.load(response)
        except urllib.error.HTTPError as error:
            try:
                reply = json.load(error)
            except ValueError:
                raise TelegramError(f"HTTP {error.code}", error.code) from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            # The reason, never the address: the address holds the token.
            reason = getattr(error, "reason", error)
            raise TelegramError(f"network: {reason}") from None
        if not reply.get("ok"):
            parameters = _obj(reply.get("parameters"))
            raise TelegramError(
                str(reply.get("description", "error")),
                int(reply.get("error_code", 0)),
                parameters.get("retry_after"),
            )
        return reply.get("result")


class Telegram:
    name = PLATFORM

    def __init__(self, api: TelegramApi, *, names: Sequence[str] = DEFAULT_NAMES) -> None:
        self._api = api
        self._me_id = 0
        self.username = ""
        self.names = [name.strip().lower() for name in names if name.strip()]
        self._offset = 0
        self._live = LiveMessages(
            self._put,
            every=lambda place, view: DRAFT_EVERY_S if _drafts(place, view) else EDIT_EVERY_S,
            retry_after=lambda error: (
                error.retry_after if isinstance(error, TelegramError) else None
            ),
        )

    @property
    def identity(self) -> str:
        return f"@{self.username}" if self.username else ""

    async def start(self) -> None:
        if self._me_id:
            return
        try:
            me = await self._api.call("getMe")
        except TelegramError as error:
            if error.code in (401, 404):
                raise AuthError("Telegram does not know this token") from None
            raise
        self._me_id = int(me["id"])
        self.username = str(me.get("username", ""))
        first = str(me.get("first_name", "")).strip().lower()
        if first and first not in self.names:
            self.names.append(first)
        try:
            await self._api.call(
                "setMyCommands",
                commands=[{"command": name, "description": text} for name, text in COMMANDS],
            )
        except TelegramError as error:
            log.warning("telegram.commands_failed", error=str(error))

    async def incoming(self) -> AsyncIterator[Incoming]:
        delay = 1.0
        while True:
            try:
                updates = await self._api.call(
                    "getUpdates",
                    wait_s=POLL_S + 10,
                    offset=self._offset or None,
                    timeout=POLL_S,
                    allowed_updates=["message", "callback_query", "stopped_message_generation"],
                )
                delay = 1.0
            except TelegramError as error:
                if error.code in (401, 404):
                    raise AuthError("Telegram does not accept this token any more") from None
                if error.code == 409:
                    raise TelegramError(
                        "another program is reading this bot's updates; run one bridge per bot",
                        409,
                    ) from None
                log.warning("telegram.poll_failed", error=str(error))
                await asyncio.sleep(error.retry_after or delay)
                delay = min(delay * 2, 30)
                continue
            for update in updates:
                self._offset = int(update["update_id"]) + 1
                item = self.parse(update)
                if item is not None:
                    yield item

    def parse(self, update: dict[str, Any]) -> Incoming | None:
        if (message := update.get("message")) is not None:
            return self._said(message)
        if (query := update.get("callback_query")) is not None:
            message = _obj(query.get("message"))
            if not message.get("chat"):
                return None
            return Pressed(
                place=_place(message),
                person=_person(query["from"]),
                data=str(query.get("data", "")),
                query=str(query["id"]),
            )
        if (stopped := update.get("stopped_message_generation")) is not None:
            chat = stopped["chat"]
            place = _place({"chat": chat, "message_thread_id": stopped.get("message_thread_id")})
            return Pressed(place=place, person=Person(str(chat["id"]), ""), data="stop")
        return None

    def _said(self, message: dict[str, Any]) -> Said | None:
        sender = message.get("from")
        if sender is None or sender.get("is_bot"):
            return None
        text = str(message.get("text") or message.get("caption") or "")
        if not text:
            return None
        place = _place(message)
        mention = f"@{self.username}".lower() if self.username else None
        addressed = place.private
        if text.startswith("/"):
            command, _, rest = text.partition(" ")
            name, _, target = command.partition("@")
            if target and target.lower() != self.username.lower():
                return None
            text = f"{name} {rest}".strip()
            addressed = True
        if mention and mention in text.lower():
            addressed = True
            text = re.sub(re.escape(mention), "", text, flags=re.IGNORECASE).strip()
        elif (rest := _called(text, self.names)) is not None:
            addressed = True
            text = rest
        replied = _obj(message.get("reply_to_message"))
        if _obj(replied.get("from")).get("id") == self._me_id:
            addressed = True
        return Said(
            place=place,
            person=_person(sender),
            text=text,
            addressed=addressed,
            ref=str(message["message_id"]),
        )

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
        self,
        place: Place,
        shown: Slot,
        view: Answer | Notice,
        final: bool,
        reply_to: str | None,
    ) -> None:
        live = _drafts(place, view) and not final
        markdown = render(view, thinking_tag=live)
        keyboard = _keyboard(view, place)
        if live:
            await self._api.call(
                "sendRichMessageDraft",
                **_where(place),
                draft_id=_draft_id(place, shown),
                rich_message={"markdown": _clip(markdown)},
                can_stop=True,
            )
            return
        parts = _split(markdown) if final else [_clip(markdown)]
        first, rest = parts[0], parts[1:]
        if shown.message_id is None:
            shown.message_id = await self._send(
                place, first, keyboard if not rest else None, reply_to
            )
        elif first + json.dumps(keyboard) != shown.sent:
            await self._edit(place, shown.message_id, first, keyboard if not rest else None)
        shown.sent = first + json.dumps(keyboard)
        for index, part in enumerate(rest):
            last = index == len(rest) - 1
            await self._send(place, part, keyboard if last else None, None)

    async def _send(
        self, place: Place, markdown: str, keyboard: dict[str, Any] | None, reply_to: str | None
    ) -> int:
        reply = (
            {"message_id": int(reply_to), "allow_sending_without_reply": True} if reply_to else None
        )
        try:
            sent = await self._api.call(
                "sendRichMessage",
                **_where(place),
                rich_message={"markdown": markdown},
                reply_markup=keyboard,
                reply_parameters=reply,
            )
        except TelegramError as error:
            if error.code != 400 or "not modified" in str(error).lower():
                raise
            # Markdown Telegram could not read: the same words, as plain text.
            sent = await self._api.call(
                "sendMessage",
                **_where(place),
                text=plain(markdown),
                reply_markup=keyboard,
                reply_parameters=reply,
            )
        return int(sent["message_id"])

    async def _edit(
        self, place: Place, message_id: int, markdown: str, keyboard: dict[str, Any] | None
    ) -> None:
        markup = keyboard or {"inline_keyboard": []}
        try:
            await self._api.call(
                "editMessageText",
                chat_id=place.chat,
                message_id=message_id,
                rich_message={"markdown": markdown},
                reply_markup=markup,
            )
        except TelegramError as error:
            text = str(error).lower()
            if "not modified" in text:
                return
            if error.code != 400:
                raise
            await self._api.call(
                "editMessageText",
                chat_id=place.chat,
                message_id=message_id,
                text=plain(markdown),
                reply_markup=markup,
            )

    async def answer(self, pressed: Pressed, text: str = "", *, alert: bool = False) -> None:
        if pressed.query is None:
            return
        try:
            await self._api.call(
                "answerCallbackQuery",
                callback_query_id=pressed.query,
                text=text[:200] or None,
                show_alert=alert or None,
            )
        except TelegramError as error:
            log.info("telegram.answer_failed", error=str(error))

    async def close(self) -> None:
        await self._live.close()


def render(view: Answer | Notice, *, thinking_tag: bool = False) -> str:
    """Rich Markdown for a view. Text from the agent is Markdown already and goes as it is;
    names and commands are escaped."""
    if isinstance(view, Notice):
        return view.text
    parts: list[str] = []
    if view.asked_by and view.question:
        question = " ".join(view.question.split())
        if len(question) > 300:
            question = question[:299] + "…"
        parts.append(f">**{escape(view.asked_by)}:** {escape(question)}")
    if view.steps:
        parts.append(_steps(view))
    if view.text.strip():
        parts.append(view.text.strip())
    elif not view.finished:
        parts.append("<tg-thinking>Thinking…</tg-thinking>" if thinking_tag else "_Thinking…_")
    match view.phase:
        case Phase.STOPPED:
            parts.append("_⏹ Stopped._")
        case Phase.FAILED:
            reason = f": {escape(view.error)}" if view.error else ""
            parts.append(f"⚠️ **The run failed**{reason}")
        case Phase.DONE if not view.text.strip():
            parts.append("_Done._")
        case _:
            pass
    return "\n\n".join(parts)


def _steps(view: Answer) -> str:
    running = any(step.state is StepState.RUNNING for step in view.steps)
    count = len(view.steps)
    summary = f"🛠 {count} step{'s' if count != 1 else ''}" + (" · working" if running else "")
    shown = view.steps[-MAX_STEPS:]
    lines: list[str] = []
    if count > len(shown):
        lines.append(f"- … {count - len(shown)} earlier")
    for step in shown:
        subject = " ".join(step.subject.split())
        if len(subject) > 80:
            subject = subject[:79] + "…"
        lines.append(
            f"- {ICON[step.state]} {code(step.tool)} {code(subject) if subject else ''}".rstrip()
        )
    return f"<details><summary>{summary}</summary>\n\n" + "\n".join(lines) + "\n\n</details>"


def escape(text: str) -> str:
    return _ESCAPED.sub(r"\\\1", text)


def code(text: str) -> str:
    if not text:
        return ""
    ticks = "``" if "`" in text else "`"
    pad = " " if ticks == "``" else ""
    return f"{ticks}{pad}{text}{pad}{ticks}"


def plain(markdown: str) -> str:
    text = re.sub(r"</?(details|summary|tg-thinking)[^>]*>", "", markdown)
    return text[:MAX_PLAIN]


def _keyboard(view: Answer | Notice, place: Place) -> dict[str, Any] | None:
    if isinstance(view, Answer):
        if view.finished or place.private:
            return None
        return {
            "inline_keyboard": [[{"text": "⏹ Stop", "callback_data": "stop", "style": "danger"}]]
        }
    if not view.choices:
        return None
    rows = [
        [
            {"text": choice.label, "callback_data": choice.data}
            | ({"style": STYLE[choice.tone]} if choice.tone in STYLE else {})
            for choice in row
        ]
        for row in view.choices
    ]
    return {"inline_keyboard": rows}


def _drafts(place: Place, view: Answer | Notice) -> bool:
    return place.private and isinstance(view, Answer)


def _draft_id(place: Place, shown: Slot) -> int:
    digest = hashlib.sha256(f"{place.key}:{id(shown)}".encode()).digest()
    return int.from_bytes(digest[:4]) % 2_000_000_000 + 1


def _where(place: Place) -> dict[str, Any]:
    where: dict[str, Any] = {"chat_id": int(place.chat) if _numeric(place.chat) else place.chat}
    if place.thread:
        where["message_thread_id"] = int(place.thread)
    return where


def _numeric(value: str) -> bool:
    return value.lstrip("-").isdigit()


def _clip(markdown: str) -> str:
    return markdown if len(markdown) <= MAX_RICH else markdown[: MAX_RICH - 1] + "…"


def _split(markdown: str) -> list[str]:
    """Pieces under Telegram's limit, cut between paragraphs where it can."""
    parts: list[str] = []
    rest = markdown
    while len(rest) > MAX_RICH:
        cut = rest.rfind("\n\n", 0, MAX_RICH)
        if cut < MAX_RICH // 2:
            cut = MAX_RICH
        parts.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    parts.append(rest)
    return parts


def _place(message: dict[str, Any]) -> Place:
    chat = message["chat"]
    thread = message.get("message_thread_id")
    topic = thread is not None and (
        message.get("is_topic_message") or chat.get("is_forum") or chat.get("type") == "private"
    )
    return Place(
        platform=PLATFORM,
        chat=str(chat["id"]),
        thread=str(thread) if topic else None,
        private=chat.get("type") == "private",
    )


def _person(user: dict[str, Any]) -> Person:
    name = " ".join(part for part in (user.get("first_name"), user.get("last_name")) if part)
    return Person(id=str(user["id"]), name=name or str(user.get("username") or user["id"]))


def _obj(value: object) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _called(text: str, names: Sequence[str]) -> str | None:
    """What is left of a message that starts by calling the bot by name, or None."""
    lowered = text.lower()
    for name in sorted(names, key=len, reverse=True):
        if lowered.startswith(name) and (len(text) == len(name) or not text[len(name)].isalnum()):
            return text[len(name) :].lstrip(" ,:;!-—–").strip()
    return None
