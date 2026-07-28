"""Async boundaries for synchronous framework work."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from functools import partial
from typing import Any, Callable

_BLOCKING_EXECUTOR = ThreadPoolExecutor(thread_name_prefix="agno-blocking")


async def run_blocking(
    function: Callable[..., Any],
    /,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Run synchronous work with context propagation and settled cancellation."""

    loop = asyncio.get_running_loop()
    context = copy_context()
    future = loop.run_in_executor(
        _BLOCKING_EXECUTOR,
        partial(context.run, partial(function, *args, **kwargs)),
    )
    cancellation: asyncio.CancelledError | None = None
    while not future.done():
        try:
            # Polling also covers runtimes that can miss the cross-thread
            # wakeup after a worker completes in a short-lived event loop.
            await asyncio.wait_for(asyncio.shield(future), timeout=0.01)
        except TimeoutError:
            continue
        except asyncio.CancelledError as exc:
            if future.cancelled():
                raise
            if cancellation is None:
                cancellation = exc

    result = future.result()
    if cancellation is not None:
        raise cancellation
    return result


__all__ = ["run_blocking"]
