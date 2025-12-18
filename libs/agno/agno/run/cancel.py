"""Run cancellation management."""

import asyncio
import threading
from typing import Dict

from agno.exceptions import RunCancelledException
from agno.utils.log import logger


class RunCancellationManager:
    """Manages cancellation state for agent runs.

    This class can be extended to implement custom cancellation logic.
    Use set_cancellation_manager() to replace the global instance with your own.
    """

    def __init__(self):
        self._cancelled_runs: Dict[str, bool] = {}
        self._lock = threading.Lock()
        self._async_lock = asyncio.Lock()

    def register_run(self, run_id: str) -> None:
        """Register a new run as not cancelled."""
        with self._lock:
            self._cancelled_runs[run_id] = False

    async def aregister_run(self, run_id: str) -> None:
        """Register a new run as not cancelled (async version)."""
        async with self._async_lock:
            self._cancelled_runs[run_id] = False

    def cancel_run(self, run_id: str) -> bool:
        """Cancel a run by marking it as cancelled.

        Returns:
            bool: True if run was found and cancelled, False if run not found.
        """
        with self._lock:
            if run_id in self._cancelled_runs:
                self._cancelled_runs[run_id] = True
                logger.info(f"Run {run_id} marked for cancellation")
                return True
            else:
                logger.warning(f"Attempted to cancel unknown run {run_id}")
                return False

    async def acancel_run(self, run_id: str) -> bool:
        """Cancel a run by marking it as cancelled (async version).

        Returns:
            bool: True if run was found and cancelled, False if run not found.
        """
        async with self._async_lock:
            if run_id in self._cancelled_runs:
                self._cancelled_runs[run_id] = True
                logger.info(f"Run {run_id} marked for cancellation")
                return True
            else:
                logger.warning(f"Attempted to cancel unknown run {run_id}")
                return False

    def is_cancelled(self, run_id: str) -> bool:
        """Check if a run is cancelled."""
        with self._lock:
            return self._cancelled_runs.get(run_id, False)

    async def ais_cancelled(self, run_id: str) -> bool:
        """Check if a run is cancelled (async version)."""
        async with self._async_lock:
            return self._cancelled_runs.get(run_id, False)

    def cleanup_run(self, run_id: str) -> None:
        """Remove a run from tracking (called when run completes)."""
        with self._lock:
            if run_id in self._cancelled_runs:
                del self._cancelled_runs[run_id]

    async def acleanup_run(self, run_id: str) -> None:
        """Remove a run from tracking (called when run completes) (async version)."""
        async with self._async_lock:
            if run_id in self._cancelled_runs:
                del self._cancelled_runs[run_id]

    def raise_if_cancelled(self, run_id: str) -> None:
        """Check if a run should be cancelled and raise exception if so."""
        if self.is_cancelled(run_id):
            logger.info(f"Cancelling run {run_id}")
            raise RunCancelledException(f"Run {run_id} was cancelled")

    async def araise_if_cancelled(self, run_id: str) -> None:
        """Check if a run should be cancelled and raise exception if so (async version)."""
        if await self.ais_cancelled(run_id):
            logger.info(f"Cancelling run {run_id}")
            raise RunCancelledException(f"Run {run_id} was cancelled")

    def get_active_runs(self) -> Dict[str, bool]:
        """Get all currently tracked runs and their cancellation status."""
        with self._lock:
            return self._cancelled_runs.copy()

    async def aget_active_runs(self) -> Dict[str, bool]:
        """Get all currently tracked runs and their cancellation status (async version)."""
        async with self._async_lock:
            return self._cancelled_runs.copy()


# Global cancellation manager instance
_cancellation_manager = RunCancellationManager()


def set_cancellation_manager(manager: RunCancellationManager) -> None:
    """Set a custom cancellation manager.

    Args:
        manager: A RunCancellationManager instance or subclass.

    Example:
        ```python
        class MyCustomManager(RunCancellationManager):
            def cancel_run(self, run_id: str) -> bool:
                # Custom cancellation logic
                logger.info(f"Custom cancellation for {run_id}")
                return super().cancel_run(run_id)

        set_cancellation_manager(MyCustomManager())
        ```
    """
    global _cancellation_manager
    _cancellation_manager = manager
    logger.info(f"Cancellation manager set to {type(manager).__name__}")


def get_cancellation_manager() -> RunCancellationManager:
    """Get the current cancellation manager instance.

    Returns:
        The current RunCancellationManager instance.
    """
    return _cancellation_manager


def register_run(run_id: str) -> None:
    """Register a new run for cancellation tracking."""
    _cancellation_manager.register_run(run_id)


async def aregister_run(run_id: str) -> None:
    """Register a new run for cancellation tracking (async version)."""
    await _cancellation_manager.aregister_run(run_id)


def cancel_run(run_id: str) -> bool:
    """Cancel a run."""
    return _cancellation_manager.cancel_run(run_id)


async def acancel_run(run_id: str) -> bool:
    """Cancel a run (async version)."""
    return await _cancellation_manager.acancel_run(run_id)


def is_cancelled(run_id: str) -> bool:
    """Check if a run is cancelled."""
    return _cancellation_manager.is_cancelled(run_id)


async def ais_cancelled(run_id: str) -> bool:
    """Check if a run is cancelled (async version)."""
    return await _cancellation_manager.ais_cancelled(run_id)


def cleanup_run(run_id: str) -> None:
    """Clean up cancellation tracking for a completed run."""
    _cancellation_manager.cleanup_run(run_id)


async def acleanup_run(run_id: str) -> None:
    """Clean up cancellation tracking for a completed run (async version)."""
    await _cancellation_manager.acleanup_run(run_id)


def raise_if_cancelled(run_id: str) -> None:
    """Check if a run should be cancelled and raise exception if so."""
    _cancellation_manager.raise_if_cancelled(run_id)


async def araise_if_cancelled(run_id: str) -> None:
    """Check if a run should be cancelled and raise exception if so (async version)."""
    await _cancellation_manager.araise_if_cancelled(run_id)


def get_active_runs() -> Dict[str, bool]:
    """Get all currently tracked runs and their cancellation status."""
    return _cancellation_manager.get_active_runs()


async def aget_active_runs() -> Dict[str, bool]:
    """Get all currently tracked runs and their cancellation status (async version)."""
    return await _cancellation_manager.aget_active_runs()
