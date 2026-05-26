"""Run cancellation management."""

import asyncio
from typing import Dict, Set

from agno.run.cancellation_management.base import BaseRunCancellationManager
from agno.run.cancellation_management.in_memory_cancellation_manager import InMemoryRunCancellationManager
from agno.utils.log import logger

# Global cancellation manager instance
_cancellation_manager: BaseRunCancellationManager = InMemoryRunCancellationManager()

# Per team run_id, the async delegate tasks the model spawned. The team's cancel
# handler awaits these before persisting so each member's post-cancel
# add_member_run lands on run_response in time.
_member_drain_tasks: Dict[str, Set[asyncio.Task]] = {}


def set_cancellation_manager(manager: BaseRunCancellationManager) -> None:
    """Set a custom cancellation manager.

    Args:
        manager: A BaseRunCancellationManager instance or subclass.

    Example:
        ```python
        class MyCustomManager(BaseRunCancellationManager):
            ....

        set_cancellation_manager(MyCustomManager())
        ```
    """
    global _cancellation_manager
    _cancellation_manager = manager
    logger.info(f"Cancellation manager set to {type(manager).__name__}")


def get_cancellation_manager() -> BaseRunCancellationManager:
    """Get the current cancellation manager instance."""
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


def register_member_run(team_run_id: str, member_run_id: str) -> None:
    """Record that a member run belongs to a team run for cancel-cascade."""
    _cancellation_manager.register_member_run(team_run_id, member_run_id)


async def aregister_member_run(team_run_id: str, member_run_id: str) -> None:
    """Record that a member run belongs to a team run for cancel-cascade (async version)."""
    await _cancellation_manager.aregister_member_run(team_run_id, member_run_id)


def get_member_run_ids(team_run_id: str) -> Set[str]:
    """Return the in-flight member run_ids of a team run."""
    return _cancellation_manager.get_member_run_ids(team_run_id)


async def aget_member_run_ids(team_run_id: str) -> Set[str]:
    """Return the in-flight member run_ids of a team run (async version)."""
    return await _cancellation_manager.aget_member_run_ids(team_run_id)


def cleanup_member_runs(team_run_id: str) -> None:
    """Drop a team run's member tracking when the team run finishes."""
    _cancellation_manager.cleanup_member_runs(team_run_id)
    _member_drain_tasks.pop(team_run_id, None)


async def acleanup_member_runs(team_run_id: str) -> None:
    """Drop a team run's member tracking when the team run finishes (async version)."""
    await _cancellation_manager.acleanup_member_runs(team_run_id)
    _member_drain_tasks.pop(team_run_id, None)


def register_member_drain_task(team_run_id: str, task: asyncio.Task) -> None:
    """Track an async delegate task so its post-cancel cleanup can be awaited."""
    _member_drain_tasks.setdefault(team_run_id, set()).add(task)
    task.add_done_callback(lambda t: _member_drain_tasks.get(team_run_id, set()).discard(t))


async def adrain_member_tasks(team_run_id: str, timeout: float = 5.0) -> None:
    """Await all in-flight delegate tasks for a team run, bounded by timeout."""
    tasks = {t for t in _member_drain_tasks.get(team_run_id, set()) if not t.done()}
    if not tasks:
        return
    try:
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning(f"Timed out draining {len(tasks)} member task(s) for run {team_run_id}")
