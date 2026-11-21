"""The chat services a bridge can talk through, described as data.

A provider says what it is, what a person must give it (a token, an application id) and how to
build the `ChatPlatform` from those values. Everything that shows a provider (the web client, the
terminal, the CLI) renders this description, so a new service is one `Provider` and one platform
module: no screen changes.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from plural.bridge.platform import ChatPlatform

Values = Mapping[str, str]


@dataclass(frozen=True, slots=True)
class Field:
    id: str
    label: str
    secret: bool = False
    required: bool = True
    help: str = ""
    placeholder: str = ""

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "secret": self.secret,
            "required": self.required,
            "help": self.help,
            "placeholder": self.placeholder,
        }


NAMES = Field(
    "names",
    "Names that call the bot",
    required=False,
    help="Words that start a message meant for the bot, separated by commas. "
    "Empty: plural, плюрал, плурал and the bot's own name.",
    placeholder="plural, bot",
)


@dataclass(frozen=True, slots=True)
class Provider:
    id: str
    label: str
    summary: str
    fields: tuple[Field, ...]
    build: Callable[[Values], ChatPlatform]
    steps: tuple[str, ...] = field(default=())

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "summary": self.summary,
            "steps": list(self.steps),
            "fields": [item.to_json() for item in self.fields],
        }


def names_of(values: Values) -> list[str]:
    return [word.strip() for word in values.get("names", "").split(",") if word.strip()]


class Registry:
    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}

    def register(self, provider: Provider) -> None:
        if provider.id in self._providers:
            raise ValueError(f"provider {provider.id} is already registered")
        self._providers[provider.id] = provider

    def get(self, provider_id: str) -> Provider | None:
        return self._providers.get(provider_id)

    def all(self) -> list[Provider]:
        return list(self._providers.values())
