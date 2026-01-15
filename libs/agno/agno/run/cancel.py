"""Run cancellation management."""

from typing import Dict

from agno.run.cancellation_management.base import BaseRunCancellationManager
from agno.run.cancellation_management.in_memory_cancellation_manager import InMemoryRunCancellationManager
from agno.utils.log import logger

# Global cancellation manager instance
_cancellation_manager: BaseRunCancellationManager = InMemoryRunCancellationManager()


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
