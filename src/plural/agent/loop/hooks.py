"""What the host may change in a loop's work, such as through its plugins.

The loop calls these at fixed points and goes on with what they return. A host without
hooks passes `NoHooks`, which changes nothing.
"""

from collections.abc import Sequence
from typing import Protocol

from plural.agent.loop.messages import Message
from plural.agent.providers.base import LlmRequest, ToolCallRequest
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

    async def request(self, request: LlmRequest) -> LlmRequest:
        """The request the model is sent in place of `request`, before each model call."""
        ...

    async def summary(self, history: Sequence[Message], previous: str | None) -> str | None:
        """A summary of `history` to compact it with, in place of the model's; None lets the
        model write it. `previous` is the summary an earlier compaction left."""
        ...


class NoHooks:
    async def tool_args(self, call: ToolCallRequest, provenance: Provenance) -> ToolCallRequest:
        return call

    async def tool_result(
        self, call: ToolCallView, result: ToolResult, provenance: Provenance
    ) -> ToolResult:
        return result

    async def request(self, request: LlmRequest) -> LlmRequest:
        return request

    async def summary(self, history: Sequence[Message], previous: str | None) -> str | None:
        return None
