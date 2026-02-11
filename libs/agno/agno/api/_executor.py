"""Shared background executor for fire-and-forget telemetry."""

from __future__ import annotations

import atexit
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

_telemetry_executor: Optional[ThreadPoolExecutor] = None


def get_telemetry_executor() -> ThreadPoolExecutor:
    """Lazy-initialize a module-level daemon thread pool for telemetry.

    Uses max_workers=2 since telemetry is low-volume (one event per run).
    """
    global _telemetry_executor
    if _telemetry_executor is None:
        _telemetry_executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="agno-telemetry",
        )
        atexit.register(_shutdown_telemetry_executor)
    return _telemetry_executor


def _shutdown_telemetry_executor() -> None:
    """Best-effort shutdown: cancel pending futures, don't block."""
    global _telemetry_executor
    if _telemetry_executor is not None:
        _telemetry_executor.shutdown(wait=False)
        _telemetry_executor = None
