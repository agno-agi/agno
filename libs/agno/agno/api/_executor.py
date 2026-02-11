"""Shared background executor for fire-and-forget telemetry."""

from __future__ import annotations

import asyncio
import atexit
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Coroutine, Optional

from agno.utils.log import log_debug

_telemetry_executor: Optional[ThreadPoolExecutor] = None
_executor_lock = threading.Lock()


def get_telemetry_executor() -> ThreadPoolExecutor:
    """Lazy-initialize a module-level daemon thread pool for telemetry.

    Uses max_workers=2 since telemetry is low-volume (one event per run).
    Thread-safe via double-checked locking.
    """
    global _telemetry_executor
    if _telemetry_executor is None:
        with _executor_lock:
            if _telemetry_executor is None:
                _telemetry_executor = ThreadPoolExecutor(
                    max_workers=2,
                    thread_name_prefix="agno-telemetry",
                )
                atexit.register(_shutdown_telemetry_executor)
    return _telemetry_executor


def fire_and_forget_async(coro: Coroutine[Any, Any, Any]) -> None:
    """Schedule a coroutine as a fire-and-forget task on the running event loop.

    Falls back to the thread pool executor if no event loop is running.
    """
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(coro)
        task.add_done_callback(_log_task_exception)
    except RuntimeError:
        # No running event loop — fall back to thread pool.
        # This shouldn't happen in normal async flows but guards against edge cases.
        get_telemetry_executor().submit(_run_coro_sync, coro)


def _log_task_exception(task: asyncio.Task[Any]) -> None:
    """Log exceptions from fire-and-forget tasks instead of silently dropping them."""
    if not task.cancelled() and task.exception() is not None:
        log_debug(f"Telemetry task failed: {task.exception()}")


def _run_coro_sync(coro: Coroutine[Any, Any, Any]) -> None:
    """Run a coroutine synchronously — used as fallback when no event loop is available."""
    asyncio.run(coro)


def _shutdown_telemetry_executor() -> None:
    """Best-effort shutdown: cancel pending futures, don't block."""
    global _telemetry_executor
    if _telemetry_executor is not None:
        _telemetry_executor.shutdown(wait=False)
        _telemetry_executor = None
