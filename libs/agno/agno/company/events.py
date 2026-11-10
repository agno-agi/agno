"""Wake Task event streams when a Task changes in this process.

Streams also re-read their Tasks on a short interval, so a change made by another
replica, or missed while a client reconnected, still reaches them. This only makes a
change on this replica arrive at once.
"""

import asyncio
from typing import Set

_waiters: Set[asyncio.Event] = set()


def notify_task_changed() -> None:
    for waiter in list(_waiters):
        waiter.set()


async def wait_for_task_change(timeout: float) -> None:
    waiter = asyncio.Event()
    _waiters.add(waiter)
    try:
        await asyncio.wait_for(waiter.wait(), timeout)
    except asyncio.TimeoutError:
        pass
    finally:
        _waiters.discard(waiter)
