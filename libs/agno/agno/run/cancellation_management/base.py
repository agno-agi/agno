from abc import ABC, abstractmethod
from typing import Dict, Optional, Set


class BaseRunCancellationManager(ABC):
    """Manages cancellation state for agent runs.

    This class can be extended to implement custom cancellation logic.
    Use set_cancellation_manager() to replace the global instance with your own.
    """

    @abstractmethod
    def register_run(self, run_id: str) -> None:
        """Register a new run as not cancelled."""
        pass

    @abstractmethod
    async def aregister_run(self, run_id: str) -> None:
        """Register a new run as not cancelled (async version)."""
        pass

    @abstractmethod
    def cancel_run(self, run_id: str) -> bool:
        """Cancel a run by marking it as cancelled.

        Always stores cancellation intent, even for runs not yet registered
        (cancel-before-start support for background runs).

        Returns:
            bool: True if run was previously registered, False if storing
            cancellation intent for an unregistered run.
        """
        pass

    @abstractmethod
    async def acancel_run(self, run_id: str) -> bool:
        """Cancel a run by marking it as cancelled (async version).

        Always stores cancellation intent, even for runs not yet registered
        (cancel-before-start support for background runs).

        Returns:
            bool: True if run was previously registered, False if storing
            cancellation intent for an unregistered run.
        """
        pass

    @abstractmethod
    def is_cancelled(self, run_id: str) -> bool:
        """Check if a run is cancelled."""
        pass

    @abstractmethod
    async def ais_cancelled(self, run_id: str) -> bool:
        """Check if a run is cancelled (async version)."""
        pass

    @abstractmethod
    def cleanup_run(self, run_id: str) -> None:
        """Remove a run from tracking (called when run completes)."""
        pass

    @abstractmethod
    async def acleanup_run(self, run_id: str) -> None:
        """Remove a run from tracking (called when run completes) (async version)."""
        pass

    # -- Token-scoped cleanup (generation-scoped, for accept-side cleanup) --
    # A cancel mints an opaque token; cleanup-if-token deletes intent ONLY if
    # the stored token still equals the one the caller observed - so a
    # cleanup delayed arbitrarily (stalled coroutine, crashed-then-resumed
    # process) can never erase a NEWER cancellation. Equality, not ordering:
    # no clocks, no counters. Defaults are the SAFE direction for custom
    # managers that do not implement tokens: no token -> callers skip the
    # conditional cleanup -> stale intent may cancel a continuation leg
    # visibly (operator requeue remedies), but a legitimate cancel is never
    # erased.

    def get_cancellation_token(self, run_id: str) -> Optional[str]:
        """Return the current cancellation intent's opaque token, or None if
        the run has no cancellation intent (or tokens are unsupported)."""
        return None

    async def aget_cancellation_token(self, run_id: str) -> Optional[str]:
        """Async variant of get_cancellation_token."""
        return None

    def cleanup_run_if_token(self, run_id: str, token: str) -> bool:
        """Atomically remove cancellation intent ONLY if its token still
        equals ``token``. Returns True if intent was removed."""
        return False

    async def acleanup_run_if_token(self, run_id: str, token: str) -> bool:
        """Async variant of cleanup_run_if_token."""
        return False

    @abstractmethod
    def raise_if_cancelled(self, run_id: str) -> None:
        """Check if a run should be cancelled and raise exception if so."""
        pass

    @abstractmethod
    async def araise_if_cancelled(self, run_id: str) -> None:
        """Check if a run should be cancelled and raise exception if so (async version)."""
        pass

    @abstractmethod
    def get_active_runs(self) -> Dict[str, bool]:
        """Get all currently tracked runs and their cancellation status."""
        pass

    @abstractmethod
    async def aget_active_runs(self) -> Dict[str, bool]:
        """Get all currently tracked runs and their cancellation status (async version)."""
        pass

    # Member-run tracking (team cancel-cascade). Default no-ops so existing custom
    # managers stay instantiable; override these to support team cancel-cascade.
    def register_member_run(self, team_run_id: str, member_run_id: str) -> None:
        """Record that a member run belongs to a team run for cancel-cascade."""
        pass

    async def aregister_member_run(self, team_run_id: str, member_run_id: str) -> None:
        """Record that a member run belongs to a team run for cancel-cascade (async version)."""
        pass

    def get_member_run_ids(self, team_run_id: str) -> Set[str]:
        """Return the in-flight member run_ids of a team run."""
        return set()

    async def aget_member_run_ids(self, team_run_id: str) -> Set[str]:
        """Return the in-flight member run_ids of a team run (async version)."""
        return set()

    def cleanup_member_runs(self, team_run_id: str) -> None:
        """Drop a team run's member mapping when the team run finishes."""
        pass

    async def acleanup_member_runs(self, team_run_id: str) -> None:
        """Drop a team run's member mapping when the team run finishes (async version)."""
        pass
