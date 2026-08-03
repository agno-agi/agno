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
        # Opaque per-cancel token (uuid), minted on every cancel_run: the
        # token-scoped cleanup compares equality so a delayed cleanup can
        # never erase a newer cancel. Present only while intent is set.
        self._cancel_tokens: Dict[str, str] = {}
        self._member_runs: Dict[str, Set[str]] = {}
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
            from uuid import uuid4

            was_registered = run_id in self._cancelled_runs
            self._cancelled_runs[run_id] = True
            self._cancel_tokens[run_id] = uuid4().hex
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
            from uuid import uuid4

            with self._lock:  # one lock guards the dicts across sync AND async paths
                was_registered = run_id in self._cancelled_runs
                self._cancelled_runs[run_id] = True
                self._cancel_tokens[run_id] = uuid4().hex
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
            self._cancel_tokens.pop(run_id, None)

    async def acleanup_run(self, run_id: str) -> None:
        """Remove a run from tracking (called when run completes) (async version)."""
        async with self._async_lock:
            with self._lock:
                if run_id in self._cancelled_runs:
                    del self._cancelled_runs[run_id]
                self._cancel_tokens.pop(run_id, None)

    def get_cancellation_token(self, run_id: str):
        """Current cancellation intent's token, or None without intent."""
        with self._lock:
            if not self._cancelled_runs.get(run_id, False):
                return None
            return self._cancel_tokens.get(run_id)

    async def aget_cancellation_token(self, run_id: str):
        """Async variant of get_cancellation_token."""
        async with self._async_lock:
            with self._lock:
                if not self._cancelled_runs.get(run_id, False):
                    return None
                return self._cancel_tokens.get(run_id)

    def cleanup_run_if_token(self, run_id: str, token: str) -> bool:
        """Token-scoped cleanup: remove intent ONLY if its token still equals
        the observed one - a delayed cleanup never erases a NEWER cancel
        (which minted a different token). Atomic under the lock."""
        with self._lock:
            if not self._cancelled_runs.get(run_id, False) or self._cancel_tokens.get(run_id) != token:
                return False
            del self._cancelled_runs[run_id]
            self._cancel_tokens.pop(run_id, None)
            return True

    async def acleanup_run_if_token(self, run_id: str, token: str) -> bool:
        """Async variant of cleanup_run_if_token. The compare-and-delete runs
        under the THREADING lock: the asyncio lock only orders coroutines on
        this loop, and a sync cancel_run on another thread could otherwise
        write a NEWER token between our compare and our delete - the exact
        erase this method exists to prevent. Lock order everywhere is
        async_lock -> lock (sync paths take only lock), so no inversion."""
        async with self._async_lock:
            with self._lock:
                if not self._cancelled_runs.get(run_id, False) or self._cancel_tokens.get(run_id) != token:
                    return False
                del self._cancelled_runs[run_id]
                self._cancel_tokens.pop(run_id, None)
                return True

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

    def register_member_run(self, team_run_id: str, member_run_id: str) -> None:
        """Record that a member run belongs to a team run for cancel-cascade."""
        with self._lock:
            self._member_runs.setdefault(team_run_id, set()).add(member_run_id)

    async def aregister_member_run(self, team_run_id: str, member_run_id: str) -> None:
        """Record that a member run belongs to a team run for cancel-cascade (async version)."""
        async with self._async_lock:
            self._member_runs.setdefault(team_run_id, set()).add(member_run_id)

    def get_member_run_ids(self, team_run_id: str) -> Set[str]:
        """Return the in-flight member run_ids of a team run."""
        with self._lock:
            return set(self._member_runs.get(team_run_id, set()))

    async def aget_member_run_ids(self, team_run_id: str) -> Set[str]:
        """Return the in-flight member run_ids of a team run (async version)."""
        async with self._async_lock:
            return set(self._member_runs.get(team_run_id, set()))

    def cleanup_member_runs(self, team_run_id: str) -> None:
        """Drop a team run's member mapping when the team run finishes."""
        with self._lock:
            self._member_runs.pop(team_run_id, None)

    async def acleanup_member_runs(self, team_run_id: str) -> None:
        """Drop a team run's member mapping when the team run finishes (async version)."""
        async with self._async_lock:
            self._member_runs.pop(team_run_id, None)
