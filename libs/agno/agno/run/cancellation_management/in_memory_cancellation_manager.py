"""Run cancellation management."""

import asyncio
import threading
from typing import Dict

from agno.exceptions import RunCancelledException
from agno.run.cancellation_management.base import BaseRunCancellationManager
from agno.utils.log import logger


class InMemoryRunCancellationManager(BaseRunCancellationManager):
    def __init__(self):
        self._cancelled_runs: Dict[str, bool] = {}
        self._lock = threading.Lock()
        self._async_lock = asyncio.Lock()

    def register_run(self, run_id: str) -> None:
        """Register a new run as not cancelled.

        Uses setdefault to preserve any existing cancellation intent
        (cancel-before-start support for background runs).
        """
        with self._lock:
            self._cancelled_runs.setdefault(run_id, False)

    async def aregister_run(self, run_id: str) -> None:
        """Register a new run as not cancelled (async version).

        Uses setdefault to preserve any existing cancellation intent
        (cancel-before-start support for background runs).
        """
        async with self._async_lock:
            self._cancelled_runs.setdefault(run_id, False)

    def cancel_run(self, run_id: str) -> bool:
        """Cancel a run by marking it as cancelled.

        Always stores cancellation intent, even for runs not yet registered
        (cancel-before-start support for background runs).

        Returns:
            bool: True if run was previously registered, False if storing
            cancellation intent for an unregistered run.
        """
        with self._lock:
            was_registered = run_id in self._cancelled_runs
            self._cancelled_runs[run_id] = True
            if was_registered:
                logger.info(f"Run {run_id} marked for cancellation")
            else:
                logger.info(f"Run {run_id} not yet registered, storing cancellation intent")
            return was_registered

    async def acancel_run(self, run_id: str) -> bool:
        """Cancel a run by marking it as cancelled (async version).

        Always stores cancellation intent, even for runs not yet registered
        (cancel-before-start support for background runs).

        Returns:
            bool: True if run was previously registered, False if storing
            cancellation intent for an unregistered run.
        """
        async with self._async_lock:
            was_registered = run_id in self._cancelled_runs
            self._cancelled_runs[run_id] = True
            if was_registered:
                logger.info(f"Run {run_id} marked for cancellation")
            else:
                logger.info(f"Run {run_id} not yet registered, storing cancellation intent")
            return was_registered

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
