"""
Telemetry utilities for non-blocking telemetry submission.

This module provides a shared ThreadPoolExecutor for submitting telemetry
in the background without blocking the main execution flow.
"""

import atexit
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from agno.utils.log import log_debug

# Shared executor for all telemetry submissions
# Using max_workers=2 since telemetry is I/O bound and low volume
_telemetry_executor: Optional[ThreadPoolExecutor] = None


def _get_telemetry_executor() -> ThreadPoolExecutor:
    """Get or create the shared telemetry executor.

    The executor is lazily initialized on first use and automatically
    shut down when the program exits.
    """
    global _telemetry_executor
    if _telemetry_executor is None:
        _telemetry_executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="agno-telemetry",
        )
        # Register cleanup on program exit
        atexit.register(_shutdown_telemetry_executor)
    return _telemetry_executor


def _shutdown_telemetry_executor() -> None:
    """Shutdown the telemetry executor gracefully."""
    global _telemetry_executor
    if _telemetry_executor is not None:
        try:
            # Don't wait for pending tasks - telemetry is best-effort
            _telemetry_executor.shutdown(wait=False)
        except Exception as e:
            log_debug(f"Error shutting down telemetry executor: {e}")
        _telemetry_executor = None


def submit_telemetry(func, *args, **kwargs) -> None:
    """Submit a telemetry function to run in the background.

    Args:
        func: The telemetry function to call
        *args: Positional arguments to pass to the function
        **kwargs: Keyword arguments to pass to the function
    """
    try:
        executor = _get_telemetry_executor()
        executor.submit(func, *args, **kwargs)
    except Exception as e:
        # Don't let telemetry submission failures affect the main flow
        log_debug(f"Failed to submit telemetry: {e}")
