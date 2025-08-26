"""Run cancellation management."""

import threading
from typing import Dict

from agno.exceptions import RunCancelledException
from agno.utils.log import logger


class RunCancellationManager:
    """Manages cancellation state for agent runs."""

    def __init__(self):
        self._cancelled_runs: Dict[str, bool] = {}
        self._lock = threading.Lock()

    def register_run(self, run_id: str) -> None:
        """Register a new run as not cancelled."""
        with self._lock:
            self._cancelled_runs[run_id] = False
            logger.debug(f"Registered run {run_id} for cancellation tracking")

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

    def is_cancelled(self, run_id: str) -> bool:
        """Check if a run is cancelled."""
        with self._lock:
            return self._cancelled_runs.get(run_id, False)

    def cleanup_run(self, run_id: str) -> None:
        """Remove a run from tracking (called when run completes)."""
        with self._lock:
            if run_id in self._cancelled_runs:
                del self._cancelled_runs[run_id]
                logger.debug(f"Cleaned up cancellation tracking for run {run_id}")

    def raise_if_cancelled(self, run_id: str) -> None:
        """Check if a run should be cancelled and raise exception if so."""
        if self.is_cancelled(run_id):
            logger.info(f"Cancelling run {run_id}")
            raise RunCancelledException(f"Run {run_id} was cancelled")

    def get_active_runs(self) -> Dict[str, bool]:
        """Get all currently tracked runs and their cancellation status."""
        with self._lock:
            return self._cancelled_runs.copy()


# Global cancellation manager instance
_cancellation_manager = RunCancellationManager()


def register_run(run_id: str) -> None:
    """Register a new run for cancellation tracking."""
    _cancellation_manager.register_run(run_id)


def cancel_run(run_id: str) -> bool:
    """Cancel a run."""
    return _cancellation_manager.cancel_run(run_id)


def cleanup_run(run_id: str) -> None:
    """Clean up cancellation tracking for a completed run."""
    _cancellation_manager.cleanup_run(run_id)


def raise_if_cancelled(run_id: str) -> None:
    """Check if a run should be cancelled and raise exception if so."""
    _cancellation_manager.raise_if_cancelled(run_id)
