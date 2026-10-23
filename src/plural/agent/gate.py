from dataclasses import dataclass
from typing import Protocol

from plural.protocol.models import Provenance, ToolCallView


@dataclass(frozen=True, slots=True)
class GateResult:
    allowed: bool
    reason: str


class PolicyGate(Protocol):
    async def check(
        self, call: ToolCallView, *, subject: str, provenance: Provenance
    ) -> GateResult: ...
