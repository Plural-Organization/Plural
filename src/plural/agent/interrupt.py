import asyncio
from collections.abc import Awaitable


class Interrupted(Exception):
    pass


class TimedOut(Exception):
    pass


async def interruptible[T](
    work: Awaitable[T], cancel: asyncio.Event, timeout: float | None = None
) -> T:
    task = asyncio.ensure_future(work)
    stop = asyncio.create_task(cancel.wait())
    try:
        await asyncio.wait({task, stop}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        if task.done():
            return task.result()
        if stop.done():
            raise Interrupted
        raise TimedOut
    finally:
        for pending in (task, stop):
            if not pending.done():
                pending.cancel()
        await asyncio.gather(task, stop, return_exceptions=True)
