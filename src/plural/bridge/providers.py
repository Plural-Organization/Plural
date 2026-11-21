"""The built-in chat services. A service is added here and nowhere else."""

from plural.bridge.platform import ChatPlatform
from plural.bridge.registry import NAMES, Field, Provider, Registry, Values, names_of


def _telegram(values: Values) -> ChatPlatform:
    from plural.bridge.telegram import DEFAULT_NAMES, Telegram, TelegramApi

    return Telegram(TelegramApi(values["token"].strip()), names=names_of(values) or DEFAULT_NAMES)


def _discord(values: Values) -> ChatPlatform:
    from plural.bridge.discord import DEFAULT_NAMES, Discord, DiscordApi

    return Discord(DiscordApi(values["token"].strip()), names=names_of(values) or DEFAULT_NAMES)


TELEGRAM = Provider(
    id="telegram",
    label="Telegram",
    summary="Mention the bot in a group or write to it in private.",
    steps=(
        "Open @BotFather in Telegram and send /newbot.",
        "Copy the token it gives you and paste it here.",
        "To let the bot read the group's talk, turn privacy mode off in @BotFather "
        "(/setprivacy) or make the bot an admin of the group.",
    ),
    fields=(
        Field(
            "token",
            "Bot token",
            secret=True,
            help="From @BotFather.",
            placeholder="123456:ABC-DEF…",
        ),
        NAMES,
    ),
    build=_telegram,
)

DISCORD = Provider(
    id="discord",
    label="Discord",
    summary="Mention the bot in a server channel or write to it in a DM.",
    steps=(
        "In the Discord Developer Portal create an application and add a Bot.",
        "On the Bot page turn on Message Content Intent, then copy the bot's token.",
        "Invite the bot to your server with the bot scope and the permissions "
        "View Channels, Send Messages, Read Message History.",
    ),
    fields=(
        Field(
            "token",
            "Bot token",
            secret=True,
            help="Developer Portal → your application → Bot → Reset Token.",
            placeholder="MTA…",
        ),
        NAMES,
    ),
    build=_discord,
)


def builtin() -> Registry:
    registry = Registry()
    registry.register(TELEGRAM)
    registry.register(DISCORD)
    return registry
