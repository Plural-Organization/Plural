from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from plural.protocol.models import Provenance, ToolCallView, Usage


@dataclass(frozen=True, slots=True)
class GateResult:
    allowed: bool
    reason: str


@dataclass(frozen=True, slots=True)
class FolderResult:
    """The host's answer to a request for a folder outside the workspace."""

    granted: bool
    write: bool
    reason: str


class PolicyGate(Protocol):
    def begin_run(self) -> None: ...

    async def ask_folder(
        self, call: ToolCallView, *, folder: Path, write: bool, provenance: Provenance
    ) -> FolderResult: ...

    async def check(
        self, call: ToolCallView, *, subject: str, provenance: Provenance
    ) -> GateResult: ...

    def turn_limit(self, *, usage: Usage, provenance: Provenance) -> str | None: ...
