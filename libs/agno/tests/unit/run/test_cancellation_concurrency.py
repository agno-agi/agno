"""Sync and async cancellation calls share one process-wide state store."""

import asyncio
import inspect
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from agno.run.cancellation_management.in_memory_cancellation_manager import InMemoryRunCancellationManager


def _overlap_writes(monkeypatch, manager, first, second):
    """Pause the first write until the second completes or waits for its lock.

    The lock probe reports contention without changing mutual exclusion. This
    forces the lost-update interleaving when the methods use different locks,
    and lets the first writer finish when they correctly share one. No sleeps
    or probabilistic thread scheduling are needed.
    """
    first_paused = threading.Event()
    resume_first = threading.Event()
    second_reached = threading.Event()
    lock = manager._lock
    expires_at = manager._expires_at

    class ObservedLock:
        def __enter__(self):
            if not lock.acquire(blocking=False):
                second_reached.set()
                lock.acquire()
            return self

        def __exit__(self, *args):
            lock.release()

    def pause_first_write():
        if not first_paused.is_set():
            first_paused.set()
            assert resume_first.wait(timeout=5), "First writer was not released"
        return expires_at()

    def invoke(operation):
        result = operation()
        if inspect.isawaitable(result):
            return asyncio.run(result)
        return result

    def invoke_second():
        try:
            return invoke(second)
        finally:
            second_reached.set()

    monkeypatch.setattr(manager, "_lock", ObservedLock())
    monkeypatch.setattr(manager, "_expires_at", pause_first_write)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_result = pool.submit(invoke, first)
        try:
            assert first_paused.wait(timeout=5), "First writer did not reach the write"
            second_result = pool.submit(invoke_second)
            assert second_reached.wait(timeout=5), "Second writer did not complete or wait for the lock"
        finally:
            resume_first.set()
        first_result.result(timeout=5)
        second_result.result(timeout=5)


@pytest.mark.parametrize("register_async,cancel_async", [(False, False), (True, False), (False, True)])
def test_concurrent_registration_preserves_cancellation(monkeypatch, register_async, cancel_async):
    manager = InMemoryRunCancellationManager()
    register = manager.aregister_run if register_async else manager.register_run
    cancel = manager.acancel_run if cancel_async else manager.cancel_run

    _overlap_writes(monkeypatch, manager, lambda: register("run-1"), lambda: cancel("run-1"))

    assert manager.is_cancelled("run-1") is True
    assert asyncio.run(manager.ais_cancelled("run-1")) is True


@pytest.mark.parametrize("first_async,second_async", [(False, False), (True, False), (False, True)])
def test_concurrent_member_registration_preserves_both_members(monkeypatch, first_async, second_async):
    manager = InMemoryRunCancellationManager()
    register_first = manager.aregister_member_run if first_async else manager.register_member_run
    register_second = manager.aregister_member_run if second_async else manager.register_member_run

    _overlap_writes(
        monkeypatch,
        manager,
        lambda: register_first("team-1", "member-1"),
        lambda: register_second("team-1", "member-2"),
    )

    assert manager.get_member_run_ids("team-1") == {"member-1", "member-2"}
    assert asyncio.run(manager.aget_member_run_ids("team-1")) == {"member-1", "member-2"}
