"""Run cancellation management."""

import asyncio
import threading
from typing import Dict, Set

from agno.exceptions import RunCancelledException
from agno.run.cancellation_management.base import BaseRunCancellationManager
from agno.utils.log import logger


class InMemoryRunCancellationManager(BaseRunCancellationManager):
    def __init__(self):
        self._cancelled_runs: Dict[str, bool] = {}
        self._children_by_parent: Dict[str, Set[str]] = {}
        self._parent_by_child: Dict[str, str] = {}
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

    def _cancel_descendants(self, run_id: str) -> None:
        child_ids = list(self._children_by_parent.get(run_id, set()))
        for child_run_id in child_ids:
            self._cancelled_runs[child_run_id] = True
            self._cancel_descendants(child_run_id)

    def register_child_run(self, parent_run_id: str, child_run_id: str) -> None:
        """Track a child run and preserve already-stored parent cancellation intent."""
        with self._lock:
            self._cancelled_runs.setdefault(child_run_id, False)
            self._children_by_parent.setdefault(parent_run_id, set()).add(child_run_id)
            self._parent_by_child[child_run_id] = parent_run_id
            if self._cancelled_runs.get(parent_run_id, False):
                self._cancelled_runs[child_run_id] = True
                self._cancel_descendants(child_run_id)

    async def aregister_child_run(self, parent_run_id: str, child_run_id: str) -> None:
        """Track a child run and preserve already-stored parent cancellation intent (async version)."""
        async with self._async_lock:
            self._cancelled_runs.setdefault(child_run_id, False)
            self._children_by_parent.setdefault(parent_run_id, set()).add(child_run_id)
            self._parent_by_child[child_run_id] = parent_run_id
            if self._cancelled_runs.get(parent_run_id, False):
                self._cancelled_runs[child_run_id] = True
                self._cancel_descendants(child_run_id)

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
            self._cancel_descendants(run_id)
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
            self._cancel_descendants(run_id)
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
            parent_run_id = self._parent_by_child.pop(run_id, None)
            if parent_run_id is not None and parent_run_id in self._children_by_parent:
                self._children_by_parent[parent_run_id].discard(run_id)
                if not self._children_by_parent[parent_run_id]:
                    del self._children_by_parent[parent_run_id]
            child_run_ids = self._children_by_parent.pop(run_id, set())
            for child_run_id in child_run_ids:
                self._parent_by_child.pop(child_run_id, None)

    async def acleanup_run(self, run_id: str) -> None:
        """Remove a run from tracking (called when run completes) (async version)."""
        async with self._async_lock:
            if run_id in self._cancelled_runs:
                del self._cancelled_runs[run_id]
            parent_run_id = self._parent_by_child.pop(run_id, None)
            if parent_run_id is not None and parent_run_id in self._children_by_parent:
                self._children_by_parent[parent_run_id].discard(run_id)
                if not self._children_by_parent[parent_run_id]:
                    del self._children_by_parent[parent_run_id]
            child_run_ids = self._children_by_parent.pop(run_id, set())
            for child_run_id in child_run_ids:
                self._parent_by_child.pop(child_run_id, None)

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
