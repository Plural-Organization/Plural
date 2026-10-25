from dataclasses import dataclass
from typing import Protocol

from plural.protocol.models import Provenance, ToolCallView


@dataclass(frozen=True, slots=True)
class GateResult:
    allowed: bool
    reason: str


class PolicyGate(Protocol):
    def begin_run(self) -> None: ...

    async def check(
        self, call: ToolCallView, *, subject: str, provenance: Provenance
    ) -> GateResult: ...
