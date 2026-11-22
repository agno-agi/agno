"""Run cancellation management."""

import asyncio
import threading
import time
from typing import Dict, Optional, Set, Tuple

from agno.exceptions import RunCancelledException
from agno.run.cancellation_management.base import BaseRunCancellationManager
from agno.utils.log import logger


class InMemoryRunCancellationManager(BaseRunCancellationManager):
    """In-memory cancellation manager for single-process run cancellation.

    Args:
        ttl_seconds: TTL for entries in seconds. Defaults to 86400 (1 day).
            Entries auto-expire to prevent unbounded growth: cancel_run stores
            intent even for run ids that never start (cancel-before-start for
            background runs), and only a completing run triggers cleanup_run,
            so without a TTL each such id would occupy memory forever.
            Set to None to disable expiration. Fixed at construction: the
            expiry sweep relies on entries expiring in insertion order.
    """

    DEFAULT_TTL_SECONDS = 60 * 60 * 24  # 1 day, matching RedisRunCancellationManager

    def __init__(self, ttl_seconds: Optional[float] = DEFAULT_TTL_SECONDS):
        self.ttl_seconds = ttl_seconds
        # Both dicts keep iteration order == expiry order: every write that
        # grants a fresh TTL removes the key and re-appends it, and the TTL is
        # a per-manager constant, so stored expiry times are non-decreasing in
        # iteration order and _purge_expired only ever pops from the front.
        self._cancelled_runs: Dict[str, Tuple[bool, float]] = {}
        self._member_runs: Dict[str, Tuple[Set[str], float]] = {}
        self._lock = threading.Lock()
        self._async_lock = asyncio.Lock()
        self._clock = time.monotonic

    def _expires_at(self) -> float:
        return float("inf") if self.ttl_seconds is None else self._clock() + self.ttl_seconds

    def _purge_expired(self) -> None:
        """Drop expired entries. Must be called with the relevant lock held."""
        if self.ttl_seconds is None:
            return
        now = self._clock()
        while self._cancelled_runs:
            run_id = next(iter(self._cancelled_runs))
            if self._cancelled_runs[run_id][1] > now:
                break
            del self._cancelled_runs[run_id]
        while self._member_runs:
            team_run_id = next(iter(self._member_runs))
            if self._member_runs[team_run_id][1] > now:
                break
            del self._member_runs[team_run_id]

    def register_run(self, run_id: str) -> None:
        """Register a new run as not cancelled.

        Only creates the entry if absent, preserving any existing cancellation
        intent (cancel-before-start support for background runs). An existing
        entry keeps its original TTL.
        """
        with self._lock:
            self._purge_expired()
            if run_id not in self._cancelled_runs:
                self._cancelled_runs[run_id] = (False, self._expires_at())

    async def aregister_run(self, run_id: str) -> None:
        """Register a new run as not cancelled (async version).

        Only creates the entry if absent, preserving any existing cancellation
        intent (cancel-before-start support for background runs). An existing
        entry keeps its original TTL.
        """
        async with self._async_lock:
            self._purge_expired()
            if run_id not in self._cancelled_runs:
                self._cancelled_runs[run_id] = (False, self._expires_at())

    def cancel_run(self, run_id: str) -> bool:
        """Cancel a run by marking it as cancelled.

        Always stores cancellation intent, even for runs not yet registered
        (cancel-before-start support for background runs). The intent expires
        after ttl_seconds, so ids that never start cannot accumulate forever.

        Returns:
            bool: True if run was previously registered, False if storing
            cancellation intent for an unregistered run.
        """
        with self._lock:
            self._purge_expired()
            was_registered = run_id in self._cancelled_runs
            self._cancelled_runs.pop(run_id, None)
            self._cancelled_runs[run_id] = (True, self._expires_at())
            if was_registered:
                logger.info(f"Run {run_id} marked for cancellation")
            else:
                logger.info(f"Run {run_id} not yet registered, storing cancellation intent")
            return was_registered

    async def acancel_run(self, run_id: str) -> bool:
        """Cancel a run by marking it as cancelled (async version).

        Always stores cancellation intent, even for runs not yet registered
        (cancel-before-start support for background runs). The intent expires
        after ttl_seconds, so ids that never start cannot accumulate forever.

        Returns:
            bool: True if run was previously registered, False if storing
            cancellation intent for an unregistered run.
        """
        async with self._async_lock:
            self._purge_expired()
            was_registered = run_id in self._cancelled_runs
            self._cancelled_runs.pop(run_id, None)
            self._cancelled_runs[run_id] = (True, self._expires_at())
            if was_registered:
                logger.info(f"Run {run_id} marked for cancellation")
            else:
                logger.info(f"Run {run_id} not yet registered, storing cancellation intent")
            return was_registered

    def is_cancelled(self, run_id: str) -> bool:
        """Check if a run is cancelled."""
        with self._lock:
            self._purge_expired()
            entry = self._cancelled_runs.get(run_id)
            return entry[0] if entry is not None else False

    async def ais_cancelled(self, run_id: str) -> bool:
        """Check if a run is cancelled (async version)."""
        async with self._async_lock:
            self._purge_expired()
            entry = self._cancelled_runs.get(run_id)
            return entry[0] if entry is not None else False

    def cleanup_run(self, run_id: str) -> None:
        """Remove a run from tracking (called when run completes)."""
        with self._lock:
            self._purge_expired()
            self._cancelled_runs.pop(run_id, None)

    async def acleanup_run(self, run_id: str) -> None:
        """Remove a run from tracking (called when run completes) (async version)."""
        async with self._async_lock:
            self._purge_expired()
            self._cancelled_runs.pop(run_id, None)

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
            self._purge_expired()
            return {run_id: cancelled for run_id, (cancelled, _) in self._cancelled_runs.items()}

    async def aget_active_runs(self) -> Dict[str, bool]:
        """Get all currently tracked runs and their cancellation status (async version)."""
        async with self._async_lock:
            self._purge_expired()
            return {run_id: cancelled for run_id, (cancelled, _) in self._cancelled_runs.items()}

    def register_member_run(self, team_run_id: str, member_run_id: str) -> None:
        """Record that a member run belongs to a team run for cancel-cascade.

        Each registration refreshes the member set's TTL.
        """
        with self._lock:
            self._purge_expired()
            members, _ = self._member_runs.pop(team_run_id, (set(), 0.0))
            members.add(member_run_id)
            self._member_runs[team_run_id] = (members, self._expires_at())

    async def aregister_member_run(self, team_run_id: str, member_run_id: str) -> None:
        """Record that a member run belongs to a team run for cancel-cascade (async version).

        Each registration refreshes the member set's TTL.
        """
        async with self._async_lock:
            self._purge_expired()
            members, _ = self._member_runs.pop(team_run_id, (set(), 0.0))
            members.add(member_run_id)
            self._member_runs[team_run_id] = (members, self._expires_at())

    def get_member_run_ids(self, team_run_id: str) -> Set[str]:
        """Return the in-flight member run_ids of a team run."""
        with self._lock:
            self._purge_expired()
            entry = self._member_runs.get(team_run_id)
            return set(entry[0]) if entry is not None else set()

    async def aget_member_run_ids(self, team_run_id: str) -> Set[str]:
        """Return the in-flight member run_ids of a team run (async version)."""
        async with self._async_lock:
            self._purge_expired()
            entry = self._member_runs.get(team_run_id)
            return set(entry[0]) if entry is not None else set()

    def cleanup_member_runs(self, team_run_id: str) -> None:
        """Drop a team run's member mapping when the team run finishes."""
        with self._lock:
            self._purge_expired()
            self._member_runs.pop(team_run_id, None)

    async def acleanup_member_runs(self, team_run_id: str) -> None:
        """Drop a team run's member mapping when the team run finishes (async version)."""
        async with self._async_lock:
            self._purge_expired()
            self._member_runs.pop(team_run_id, None)
