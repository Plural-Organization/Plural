from typing import Any

import pytest

from plural.bridge.model import (
    Answer,
    Choice,
    Notice,
    Phase,
    Place,
    Pressed,
    Said,
    Step,
    StepState,
    Tone,
)
from plural.bridge.telegram import MAX_RICH, Telegram, TelegramError, render


class FakeApi:
    def __init__(self, fail: dict[str, TelegramError] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._fail = dict(fail or {})
        self._next_id = 100

    async def call(self, method: str, *, wait_s: float = 30, **params: Any) -> Any:
        self.calls.append((method, params))
        if method in self._fail:
            raise self._fail.pop(method)
        if method == "getMe":
            return {"id": 999, "username": "plural_bot"}
        if method in ("sendRichMessage", "sendMessage"):
            self._next_id += 1
            return {"message_id": self._next_id}
        return True

    def methods(self) -> list[str]:
        return [method for method, _ in self.calls]


async def bot(api: FakeApi) -> Telegram:
    telegram = Telegram(api)  # pyright: ignore[reportArgumentType]
    await telegram.start()
    return telegram


def message(
    text: str, *, chat: int = -100, kind: str = "supergroup", **extra: Any
) -> dict[str, Any]:
    return {
        "update_id": 1,
        "message": {
            "message_id": 5,
            "chat": {"id": chat, "type": kind},
            "from": {"id": 7, "first_name": "Askar", "last_name": "B"},
            "text": text,
            **extra,
        },
    }


GROUP = Place("telegram", "-100")
PRIVATE = Place("telegram", "7", private=True)


async def test_a_mention_in_a_group_is_addressed_to_the_bot_without_the_mention() -> None:
    telegram = await bot(FakeApi())

    said = telegram.parse(message("@Plural_Bot how does auth work?"))

    assert isinstance(said, Said)
    assert said.addressed
    assert said.text == "how does auth work?"
    assert said.person.name == "Askar B"
    assert said.ref == "5"


async def test_plain_group_talk_is_not_for_the_bot_but_a_reply_to_it_is() -> None:
    telegram = await bot(FakeApi())

    plain = telegram.parse(message("lunch?"))
    reply = telegram.parse(message("and tests?", reply_to_message={"from": {"id": 999}}))

    assert isinstance(plain, Said)
    assert not plain.addressed
    assert isinstance(reply, Said)
    assert reply.addressed


async def test_a_command_for_another_bot_is_ignored_and_ours_loses_the_suffix() -> None:
    telegram = await bot(FakeApi())

    assert telegram.parse(message("/link@other_bot")) is None
    ours = telegram.parse(message("/link@plural_bot now"))
    assert isinstance(ours, Said)
    assert ours.text == "/link now"
    assert ours.addressed


async def test_a_topic_is_a_place_of_its_own() -> None:
    telegram = await bot(FakeApi())

    said = telegram.parse(message("@plural_bot hi", message_thread_id=42, is_topic_message=True))

    assert isinstance(said, Said)
    assert said.place == Place("telegram", "-100", "42")


async def test_a_button_and_the_stop_of_a_draft_come_in_as_presses() -> None:
    telegram = await bot(FakeApi())
    pressed = telegram.parse(
        {
            "update_id": 2,
            "callback_query": {
                "id": "cb1",
                "from": {"id": 7, "first_name": "Askar"},
                "data": "ap:1:once",
                "message": {"message_id": 9, "chat": {"id": -100, "type": "supergroup"}},
            },
        }
    )
    stopped = telegram.parse(
        {
            "update_id": 3,
            "stopped_message_generation": {"chat": {"id": 7, "type": "private"}, "draft_id": 5},
        }
    )

    assert pressed == Pressed(GROUP, pressed.person, "ap:1:once", "cb1")  # pyright: ignore[reportOptionalMemberAccess]
    assert isinstance(stopped, Pressed)
    assert stopped.data == "stop"
    assert stopped.person.id == "7"


async def test_a_run_in_a_group_is_one_message_edited_until_it_ends() -> None:
    api = FakeApi()
    telegram = await bot(api)
    answer = Answer(asked_by="Askar", question="hi")

    await telegram.show(GROUP, "run:1", answer, final=False, reply_to="5")
    answer.text, answer.phase = "Hello!", Phase.DONE
    await telegram.show(GROUP, "run:1", answer, final=True)

    assert api.methods()[-2:] == ["sendRichMessage", "editMessageText"]
    sent, edited = api.calls[-2][1], api.calls[-1][1]
    assert sent["reply_parameters"]["message_id"] == 5
    assert sent["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "stop"
    assert edited["message_id"] == 101
    assert "Hello!" in edited["rich_message"]["markdown"]
    assert edited["reply_markup"] == {"inline_keyboard": []}


async def test_a_run_in_a_private_chat_streams_as_a_draft_then_becomes_a_message() -> None:
    api = FakeApi()
    telegram = await bot(api)
    answer = Answer()

    await telegram.show(PRIVATE, "run:1", answer, final=False)
    answer.text, answer.phase = "Done.", Phase.DONE
    await telegram.show(PRIVATE, "run:1", answer, final=True)

    assert api.methods()[-2:] == ["sendRichMessageDraft", "sendRichMessage"]
    draft = api.calls[-2][1]
    assert "<tg-thinking>" in draft["rich_message"]["markdown"]
    assert draft["can_stop"] is True


async def test_updates_closer_than_the_limit_wait_and_the_last_one_wins() -> None:
    api = FakeApi()
    telegram = await bot(api)
    answer = Answer()

    await telegram.show(GROUP, "run:1", answer, final=False)
    for word in ("one", "two", "three"):
        answer.text = word
        await telegram.show(GROUP, "run:1", answer, final=False)

    assert api.methods().count("sendRichMessage") == 1
    assert api.methods().count("editMessageText") == 0


async def test_markdown_telegram_cannot_read_goes_as_plain_text() -> None:
    api = FakeApi({"sendRichMessage": TelegramError("Bad Request: can't parse rich message", 400)})
    telegram = await bot(api)

    await telegram.show(GROUP, "say:1", Notice("**hi** <weird>"))

    assert api.methods()[-1] == "sendMessage"


async def test_an_approval_has_coloured_buttons_and_loses_them_once_answered() -> None:
    api = FakeApi()
    telegram = await bot(api)
    asking = Notice(
        "**🔐**",
        (
            (
                Choice("✅ Allow", "ap:1:once", Tone.GOOD),
                Choice("⛔ Reject", "ap:1:reject", Tone.DANGER),
            ),
        ),
    )

    await telegram.show(GROUP, "approval:a", asking)
    await telegram.show(GROUP, "approval:a", Notice("**🔐** done"))

    buttons = api.calls[-2][1]["reply_markup"]["inline_keyboard"][0]
    assert [button["style"] for button in buttons] == ["success", "danger"]
    assert api.calls[-1][0] == "editMessageText"
    assert api.calls[-1][1]["reply_markup"] == {"inline_keyboard": []}


def test_steps_fold_into_a_details_block_and_names_are_escaped() -> None:
    answer = Answer(
        asked_by="a_b*",
        question="why?",
        steps=[
            Step("1", "read", "src/a.py", StepState.OK),
            Step("2", "bash", "npm test", StepState.RUNNING),
        ],
    )

    markdown = render(answer)

    assert markdown.startswith(r">**a\_b\*:** why?")
    assert "<details><summary>🛠 2 steps · working</summary>" in markdown
    assert "- ✓ `read` `src/a.py`" in markdown
    assert "- ⏳ `bash` `npm test`" in markdown
    assert markdown.endswith("_Thinking…_")


def test_a_failed_run_says_why() -> None:
    markdown = render(Answer(phase=Phase.FAILED, error="the session went offline"))

    assert markdown.endswith("⚠️ **The run failed**: the session went offline")


async def test_a_long_answer_is_cut_into_messages_between_paragraphs() -> None:
    api = FakeApi()
    telegram = await bot(api)
    paragraph = "x" * 20_000

    await telegram.show(
        GROUP, "run:9", Answer(text=f"{paragraph}\n\n{paragraph}", phase=Phase.DONE)
    )

    sent = [
        params["rich_message"]["markdown"]
        for method, params in api.calls
        if method == "sendRichMessage"
    ]
    assert len(sent) == 2
    assert all(len(part) <= MAX_RICH for part in sent)


async def test_a_wrong_token_stops_the_bridge() -> None:
    api = FakeApi({"getUpdates": TelegramError("Unauthorized", 401)})
    telegram = await bot(api)

    with pytest.raises(TelegramError):
        async for _ in telegram.incoming():
            pass


async def test_a_message_that_starts_with_the_bots_name_is_for_it() -> None:
    telegram = await bot(FakeApi())

    called = telegram.parse(message("Плюрал, брат, работаешь?"))
    talk = telegram.parse(message("плюралистичный подход"))
    about = telegram.parse(message("в plural есть баг"))

    assert isinstance(called, Said)
    assert called.addressed
    assert called.text == "брат, работаешь?"
    assert isinstance(talk, Said)
    assert not talk.addressed
    assert isinstance(about, Said)
    assert not about.addressed
