"""Concurrency limiting for background runs.

Bounds how many background runs (``arun(background=True)`` on agents, teams and
workflows) execute concurrently. Acceptance stays unbounded: a background run
is persisted with PENDING status and its task is spawned immediately; the
limiter only gates the transition into execution. Runs beyond the limit wait in
line, still visible to pollers as PENDING.

The limit is shared across agents, teams and workflows, and is enforced per
event loop — in the standard deployment (one event loop per process, e.g.
AgentOS under uvicorn) that is a process-wide cap. A process running multiple
event loops gets one cap per loop. It can be set via the
``AGNO_BACKGROUND_MAX_CONCURRENCY`` environment variable or programmatically
(e.g. ``AgentOS(run_queue=RunQueueConfig(max_concurrency=...))``). A limit of 0 or below
disables limiting. The limit is intended to be configured once at startup;
changing it only affects runs that start waiting after the change.
"""

import asyncio
import os
from contextlib import asynccontextmanager, suppress
from typing import AsyncIterator, Optional, Tuple
from weakref import WeakKeyDictionary

from agno.exceptions import RunCancelledException
from agno.utils.log import log_warning

DEFAULT_BACKGROUND_MAX_CONCURRENCY = 32

# Idle interval after which background SSE streams emit a keepalive comment, so
# proxies do not kill connections while a run waits for a slot or is silent.
SSE_KEEPALIVE_INTERVAL_SECONDS = 15.0

_configured_limit: Optional[int] = None

# Semaphores are bound to an event loop, so cache one per loop. Keyed weakly so
# short-lived loops (e.g. in tests) do not accumulate.
_semaphores: "WeakKeyDictionary[asyncio.AbstractEventLoop, Tuple[int, asyncio.Semaphore]]" = WeakKeyDictionary()


def get_background_max_concurrency() -> int:
    """Return the current cap on concurrently executing background runs.

    A value of 0 or below means limiting is disabled.
    """
    if _configured_limit is not None:
        return _configured_limit
    env_value = os.getenv("AGNO_BACKGROUND_MAX_CONCURRENCY")
    if env_value is not None:
        try:
            return int(env_value)
        except ValueError:
            log_warning(
                f"Invalid AGNO_BACKGROUND_MAX_CONCURRENCY value {env_value!r}, "
                f"using default {DEFAULT_BACKGROUND_MAX_CONCURRENCY}"
            )
    return DEFAULT_BACKGROUND_MAX_CONCURRENCY


def set_background_max_concurrency(limit: Optional[int]) -> None:
    """Set the process-wide cap on concurrently executing background runs.

    Args:
        limit: Maximum number of background runs executing at once. 0 or below
            disables limiting. None resets to the environment variable or the
            default.
    """
    global _configured_limit
    _configured_limit = limit


@asynccontextmanager
async def background_run_slot(
    run_id: Optional[str] = None,
    cancellation_poll_interval: float = 0.5,
) -> AsyncIterator[None]:
    """Hold an execution slot for a background run.

    Waits until a slot is free when the number of executing background runs is
    at the configured limit. No-op when limiting is disabled.

    When ``run_id`` is given, cancellation is polled while waiting for a slot:
    if the run is cancelled before a slot is acquired, ``RunCancelledException``
    is raised and no slot is consumed. Cancellation after execution has started
    is the responsibility of the run itself.
    """
    limit = get_background_max_concurrency()
    if limit <= 0:
        yield
        return
    loop = asyncio.get_running_loop()
    cached = _semaphores.get(loop)
    if cached is None or cached[0] != limit:
        cached = (limit, asyncio.Semaphore(limit))
        _semaphores[loop] = cached
    semaphore = cached[1]

    if run_id is None:
        async with semaphore:
            yield
        return

    from agno.run.cancel import ais_cancelled

    # Note: each queued run polls ais_cancelled every cancellation_poll_interval
    # while waiting. This hits whatever cancellation manager is configured — free
    # for the in-memory default, but with a remote backend (e.g. Redis) a large
    # PENDING backlog means O(backlog) backend checks per interval.
    if await ais_cancelled(run_id):
        raise RunCancelledException(run_id)

    # Race the semaphore acquire against cancellation. asyncio.wait with a
    # timeout does not cancel the acquire task, so the semaphore's waiter queue
    # is only ever cancelled once, at the final decision point.
    acquire_task = asyncio.ensure_future(semaphore.acquire())
    try:
        while True:
            done, _ = await asyncio.wait({acquire_task}, timeout=cancellation_poll_interval)
            if acquire_task in done:
                acquire_task.result()
                break
            if await ais_cancelled(run_id):
                raise RunCancelledException(run_id)
    except BaseException:
        if acquire_task.done() and not acquire_task.cancelled() and acquire_task.exception() is None:
            # The acquire won the race against the exception: give the slot back
            semaphore.release()
        else:
            acquire_task.cancel()
            with suppress(asyncio.CancelledError):
                await acquire_task
            # cancel() can land after the acquire already succeeded
            if not acquire_task.cancelled() and acquire_task.exception() is None:
                semaphore.release()
        raise

    try:
        yield
    finally:
        semaphore.release()
