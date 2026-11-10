"""What every agent CLI provider shares: what it is called, how to install it and sign in, which
models it offers, and finding its binary."""

import asyncio
import shutil
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from pathlib import Path
from typing import ClassVar

from plural.agent.providers.base import LlmEvent, LlmRequest, ProviderError
from plural.agent.providers.preset import CliAdapter, Preset


class CliProvider(ABC):
    """A model behind an installed agent CLI, signed in with the CLI's own account."""

    adapter: ClassVar[CliAdapter]
    label: ClassVar[str]
    binary: ClassVar[str]
    # How to install it and sign in, for the settings screen and error messages.
    install: ClassVar[str]
    login: ClassVar[str]
    # The models offered in settings; the first is the default. None leaves the CLI's own default.
    models: ClassVar[tuple[str, ...]] = ()
    hint: ClassVar[str] = ""

    def __init__(self, *, model: str = "", workspace: Path, cli: str | None = None) -> None:
        path = cli or shutil.which(self.binary)
        if path is None:
            raise ProviderError(
                f"{self.label} is not installed: {self.install}, then {self.login}."
            )
        self._cli = path
        self._model = model or (self.models[0] if self.models else "")
        self._workspace = workspace

    @abstractmethod
    def stream(self, request: LlmRequest, *, cancel: asyncio.Event) -> AsyncIterator[LlmEvent]:
        """Stream the model's answer to one request."""

    @classmethod
    def preset(cls) -> Preset:
        return Preset(
            id=cls.adapter,
            label=cls.label,
            adapter=cls.adapter,
            models=cls.models,
            hint=cls.hint or f"Uses the installed {cls.label} and its own sign-in ({cls.login})",
            connection="oauth",
        )
