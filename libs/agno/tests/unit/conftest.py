"""Shared isolation for the unit suite."""

from pathlib import Path

import pytest

import agno.run.cancel as cancel_module
from agno.run.cancellation_management.in_memory_cancellation_manager import InMemoryRunCancellationManager


@pytest.fixture
def cp1252_default_encoding(monkeypatch):
    """Run the test as if on a Windows machine whose default text encoding is cp1252, so a
    file read or write that does not name an encoding would mangle non-ASCII text."""
    read_text = Path.read_text
    write_text = Path.write_text

    def read_text_cp1252(self, encoding=None, **kwargs):
        return read_text(self, encoding=encoding or "cp1252", **kwargs)

    def write_text_cp1252(self, data, encoding=None, **kwargs):
        return write_text(self, data, encoding=encoding or "cp1252", **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text_cp1252)
    monkeypatch.setattr(Path, "write_text", write_text_cp1252)


@pytest.fixture(autouse=True)
def isolate_run_cancellation_state():
    """Reset the process-global run-cancellation registry after every test.

    cancel_run() records cancel-before-start intent for run_ids it has never
    seen, and only a completed run's cleanup purges an entry. A test that
    cancels a run_id which never executes (e.g. POST .../runs/r1/cancel) would
    otherwise poison every later test that reuses that run_id: the later run is
    insta-cancelled instead of executing.

    Restores the manager and its explicitly-set flag directly rather than via
    set_cancellation_manager(), which would force the flag to True.
    """
    original_manager = cancel_module._cancellation_manager
    original_explicitly_set = cancel_module._cancellation_manager_explicitly_set
    yield
    cancel_module._cancellation_manager = original_manager
    cancel_module._cancellation_manager_explicitly_set = original_explicitly_set
    cancel_module._member_drain_tasks.clear()
    if isinstance(original_manager, InMemoryRunCancellationManager):
        with original_manager._lock:
            original_manager._cancelled_runs.clear()
            original_manager._member_runs.clear()
