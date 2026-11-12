"""What the host may change in a loop's work, such as through its plugins.

The loop calls these at fixed points and goes on with what they return. A host without
hooks passes `NoHooks`, which changes nothing.
"""

from typing import Protocol

from plural.agent.providers.base import ToolCallRequest
from plural.agent.tools.base import ToolResult
from plural.protocol.models import Provenance, ToolCallView


class LoopHooks(Protocol):
    async def tool_args(self, call: ToolCallRequest, provenance: Provenance) -> ToolCallRequest:
        """The call to run in place of `call`, before it is checked and put to the policy."""
        ...

    async def tool_result(
        self, call: ToolCallView, result: ToolResult, provenance: Provenance
    ) -> ToolResult:
        """The result the model gets in place of `result`, for a call that ran."""
        ...


class NoHooks:
    async def tool_args(self, call: ToolCallRequest, provenance: Provenance) -> ToolCallRequest:
        return call

    async def tool_result(
        self, call: ToolCallView, result: ToolResult, provenance: Provenance
    ) -> ToolResult:
        return result
