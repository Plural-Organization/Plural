import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from plural.bridge.discord import (
    MAX_MESSAGE,
    Discord,
    DiscordApi,
    DiscordError,
    Gateway,
    render,
    split,
)
from plural.bridge.model import (
    Answer,
    Choice,
    Notice,
    Person,
    Phase,
    Place,
    Pressed,
    Said,
    Step,
    StepState,
    Tone,
)
from plural.bridge.platform import AuthError


class FakeApi:
    token = "secret-token"

    def __init__(self, fail: dict[str, Exception] | None = None) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self._fail = dict(fail or {})
        self._next = 500

    async def call(self, method: str, path: str, body: Any = None, *, wait_s: float = 20) -> Any:
        self.calls.append((method, path, body))
        if path in self._fail:
            raise self._fail.pop(path)
        if path == "/users/@me":
            return {"id": "99", "username": "plural", "global_name": "Plural Bot"}
        if path == "/oauth2/applications/@me":
            return {"id": "77"}
        if path == "/gateway":
            return {"url": "wss://gateway.test"}
        if method == "POST" and path.endswith("/messages"):
            self._next += 1
            return {"id": str(self._next)}
        return None

    def paths(self, method: str) -> list[str]:
        return [path for kind, path, _ in self.calls if kind == method]


class FakeGateway:
    def __init__(self, events: list[tuple[str, dict[str, Any]]]) -> None:
        self._events = events

    async def events(self) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        for event in self._events:
            yield event


async def bot(api: FakeApi, events: list[tuple[str, dict[str, Any]]] | None = None) -> Discord:
    discord = Discord(
        api,  # pyright: ignore[reportArgumentType]
        gateway=lambda _url: FakeGateway(events or []),  # pyright: ignore[reportArgumentType]
    )
    await discord.start()
    return discord


def message(content: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": "5",
        "channel_id": "300",
        "guild_id": "1",
        "author": {"id": "7", "username": "askar", "global_name": "Askar"},
        "content": content,
        "mentions": [],
        **extra,
    }


GROUP = Place("discord", "300")
DM = Place("discord", "301", private=True)


async def test_start_learns_the_bot_and_registers_slash_commands() -> None:
    api = FakeApi()
    discord = await bot(api)

    assert discord.identity == "@Plural Bot"
    assert "/applications/77/commands" in api.paths("PUT")
    assert "plural bot" in discord.names


async def test_a_wrong_token_is_an_auth_error() -> None:
    api = FakeApi({"/users/@me": AuthError("no")})

    with pytest.raises(AuthError):
        await bot(api)


async def test_a_mention_is_addressed_and_the_mention_is_removed() -> None:
    discord = await bot(FakeApi())

    said = discord.parse_message(message("<@99> how does auth work?", mentions=[{"id": "99"}]))

    assert isinstance(said, Said)
    assert said.addressed
    assert said.text == "how does auth work?"
    assert said.person.name == "Askar"
    assert said.place == GROUP


async def test_talk_in_a_channel_is_not_addressed_but_a_dm_is() -> None:
    discord = await bot(FakeApi())

    talk = discord.parse_message(message("we ship on Friday"))
    direct = discord.parse_message(message("hello", guild_id=None, channel_id="301"))

    assert isinstance(talk, Said)
    assert not talk.addressed
    assert isinstance(direct, Said)
    assert direct.addressed
    assert direct.place == DM


async def test_a_reply_to_the_bot_and_a_call_by_name_are_addressed() -> None:
    discord = await bot(FakeApi())

    reply = discord.parse_message(
        message("and tests?", referenced_message={"author": {"id": "99"}})
    )
    named = discord.parse_message(message("Плюрал, брат, работаешь?"))

    assert isinstance(reply, Said)
    assert reply.addressed
    assert isinstance(named, Said)
    assert named.addressed
    assert named.text == "брат, работаешь?"


async def test_other_bots_and_empty_messages_are_ignored() -> None:
    discord = await bot(FakeApi())

    other = message("hi", author={"id": "8", "username": "bot", "bot": True})
    assert discord.parse_message(other) is None
    assert discord.parse_message(message("   ")) is None
    assert discord.parse_message(message("hi", author={"id": "99", "username": "me"})) is None


async def test_a_slash_command_and_a_button_become_said_and_pressed_and_are_acknowledged() -> None:
    api = FakeApi()
    command = {
        "id": "i1",
        "token": "tk1",
        "type": 2,
        "channel_id": "300",
        "guild_id": "1",
        "member": {"user": {"id": "7", "username": "askar"}},
        "data": {"name": "ask", "options": [{"name": "text", "value": "what changed?"}]},
    }
    button = {
        "id": "i2",
        "token": "tk2",
        "type": 3,
        "channel_id": "300",
        "guild_id": "1",
        "member": {"user": {"id": "7", "username": "askar"}},
        "data": {"custom_id": "ap:3:once"},
    }
    discord = await bot(api, [("INTERACTION_CREATE", command), ("INTERACTION_CREATE", button)])

    items = [item async for item in discord.incoming()]

    assert isinstance(items[0], Said)
    assert items[0].text == "/ask what changed?"
    assert items[0].addressed
    assert isinstance(items[1], Pressed)
    assert items[1].data == "ap:3:once"
    assert items[1].query == "tk2"
    callbacks = [path for path in api.paths("POST") if path.startswith("/interactions/")]
    assert callbacks == ["/interactions/i1/tk1/callback", "/interactions/i2/tk2/callback"]
    await asyncio.sleep(0)  # the slash command's own "thinking" reply is removed
    assert any(path.endswith("/messages/@original") for path in api.paths("DELETE"))


async def test_a_run_is_one_message_edited_in_place_and_buttons_go_when_it_ends() -> None:
    api = FakeApi()
    discord = await bot(api)
    answer = Answer(asked_by="Askar", question="fix it", text="working on it", phase=Phase.WORKING)

    await discord.show(GROUP, "run:1", answer, final=False, reply_to="5")
    answer.text = "done: fixed"
    answer.phase = Phase.DONE
    await discord.show(GROUP, "run:1", answer, final=True)

    sends = [
        body
        for method, path, body in api.calls
        if method == "POST" and path.endswith("/300/messages")
    ]
    edits = [body for method, _, body in api.calls if method == "PATCH"]
    assert len(sends) == 1
    assert sends[0]["message_reference"] == {"message_id": "5", "fail_if_not_exists": False}
    assert sends[0]["allowed_mentions"] == {"parse": []}
    assert sends[0]["components"][0]["components"][0]["custom_id"] == "stop"
    assert len(edits) == 1
    assert edits[0]["content"].endswith("done: fixed")
    assert edits[0]["components"] == []


async def test_a_notice_with_choices_becomes_styled_buttons() -> None:
    api = FakeApi()
    discord = await bot(api)
    notice = Notice(
        "**Allow?**",
        (
            (
                Choice("✅ Allow", "ap:1:once", Tone.GOOD),
                Choice("Always", "ap:1:always", Tone.PRIMARY),
            ),
            (Choice("⛔ Reject", "ap:1:reject", Tone.DANGER),),
        ),
    )

    await discord.show(GROUP, "approval:1", notice)

    body = next(body for _, path, body in api.calls if path.endswith("/300/messages"))
    rows = body["components"]
    assert [button["style"] for button in rows[0]["components"]] == [3, 1]
    assert rows[1]["components"][0]["style"] == 4
    assert rows[0]["components"][0]["custom_id"] == "ap:1:once"


async def test_words_for_the_person_who_pressed_go_out_as_a_private_follow_up() -> None:
    api = FakeApi()
    discord = await bot(api)

    pressed = Pressed(GROUP, Person("7", "Askar"), "x", query="tk")

    await discord.answer(pressed, "Only the owner", alert=True)

    method, path, body = api.calls[-1]
    assert (method, path) == ("POST", "/webhooks/77/tk")
    assert body["flags"] == 64


async def test_a_failed_final_message_is_raised_not_swallowed() -> None:
    api = FakeApi({"/channels/300/messages": DiscordError("Missing Access", 403)})
    discord = await bot(api)

    with pytest.raises(DiscordError):
        await discord.show(GROUP, "k", Notice("hi"))


@pytest.mark.parametrize(
    "code",
    ["x = 1\n" * 600, "y" * 6000],
    ids=["lines", "one long line"],
)
def test_a_long_answer_is_split_under_the_limit_and_code_fences_stay_closed(code: str) -> None:
    body = "intro\n\n```py\n" + code + "```\n\nend"

    parts = split(body)

    assert len(parts) >= 2
    assert all(len(part) <= MAX_MESSAGE for part in parts)
    assert all(part.count("```") % 2 == 0 for part in parts)


def test_render_shows_the_question_the_steps_and_the_failure() -> None:
    answer = Answer(
        asked_by="Askar",
        question="why *fails*",
        steps=[Step("c1", "bash", "pytest -q", StepState.FAILED)],
        phase=Phase.FAILED,
        error="step limit",
    )

    text = render(answer)

    assert "Askar" in text
    assert "`bash`" in text
    assert "The run failed" in text
    assert "\\*fails\\*" in text


async def test_a_discord_api_error_never_holds_the_token() -> None:
    error = DiscordError("Missing Access", 403)
    assert "secret" not in str(error)
    assert isinstance(DiscordApi("secret-token").token, str)
    _ = Gateway
