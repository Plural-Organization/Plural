import asyncio

from plural.protocol.models import ApprovalDecision


class ApprovalRegistry:
    def __init__(self) -> None:
        self._waiting: dict[str, asyncio.Future[ApprovalDecision]] = {}

    def open(self, approval_id: str) -> asyncio.Future[ApprovalDecision]:
        future: asyncio.Future[ApprovalDecision] = asyncio.get_running_loop().create_future()
        self._waiting[approval_id] = future
        return future

    def resolve(self, approval_id: str, decision: ApprovalDecision) -> bool:
        future = self._waiting.pop(approval_id, None)
        if future is None or future.done():
            return False
        future.set_result(decision)
        return True

    def discard(self, approval_id: str) -> None:
        self._waiting.pop(approval_id, None)
