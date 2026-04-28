"""Unit tests for team cascade cancellation.

Tests cover the child run mapping and cascade cancel behaviour:
1. _register_child_run / get_child_run_ids / _unregister_team_run
2. cancel_run cascades to all registered member runs
3. acancel_run cascades to all registered member runs
4. Thread-safety of the mapping
5. Cleanup on all exit paths (cancel, normal completion, unregister)
6. Edge cases (empty mapping, double unregister, non-existent keys)
"""

import asyncio
import threading
from unittest.mock import patch

import pytest

from agno.team._default_tools import (
    _child_runs,
    _child_runs_lock,
    _register_child_run,
    _unregister_team_run,
    get_child_run_ids,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def clean_child_runs():
    """Ensure _child_runs is empty before and after each test."""
    with _child_runs_lock:
        _child_runs.clear()
    yield
    with _child_runs_lock:
        _child_runs.clear()


# ============================================================================
# Unit tests: child run mapping
# ============================================================================


class TestChildRunMapping:
    """Tests for _register_child_run, get_child_run_ids, _unregister_team_run."""

    def test_register_single_child(self):
        _register_child_run("team-1", "member-1")
        assert get_child_run_ids("team-1") == {"member-1"}

    def test_register_multiple_children(self):
        _register_child_run("team-1", "member-1")
        _register_child_run("team-1", "member-2")
        _register_child_run("team-1", "member-3")
        assert get_child_run_ids("team-1") == {"member-1", "member-2", "member-3"}

    def test_register_multiple_teams(self):
        _register_child_run("team-1", "member-a")
        _register_child_run("team-2", "member-b")
        assert get_child_run_ids("team-1") == {"member-a"}
        assert get_child_run_ids("team-2") == {"member-b"}

    def test_get_child_run_ids_returns_copy(self):
        """get_child_run_ids should return a copy, not a reference."""
        _register_child_run("team-1", "member-1")
        ids = get_child_run_ids("team-1")
        ids.add("member-hacked")
        # Original should not be modified
        assert get_child_run_ids("team-1") == {"member-1"}

    def test_get_child_run_ids_empty(self):
        assert get_child_run_ids("nonexistent") == set()

    def test_unregister_team_run(self):
        _register_child_run("team-1", "member-1")
        _unregister_team_run("team-1")
        assert get_child_run_ids("team-1") == set()

    def test_unregister_nonexistent_team(self):
        """Should not raise on non-existent key."""
        _unregister_team_run("nonexistent")  # no error

    def test_double_unregister(self):
        _register_child_run("team-1", "member-1")
        _unregister_team_run("team-1")
        _unregister_team_run("team-1")  # no error
        assert get_child_run_ids("team-1") == set()

    def test_unregister_one_team_does_not_affect_other(self):
        _register_child_run("team-1", "member-a")
        _register_child_run("team-2", "member-b")
        _unregister_team_run("team-1")
        assert get_child_run_ids("team-1") == set()
        assert get_child_run_ids("team-2") == {"member-b"}

    def test_duplicate_register_same_child(self):
        """Registering the same child twice should not create duplicates."""
        _register_child_run("team-1", "member-1")
        _register_child_run("team-1", "member-1")
        assert get_child_run_ids("team-1") == {"member-1"}


# ============================================================================
# Unit tests: thread safety
# ============================================================================


class TestThreadSafety:
    """Tests for concurrent access to _child_runs."""

    def test_concurrent_registrations(self):
        """Many threads registering children for the same team should not lose any."""
        n = 100
        barrier = threading.Barrier(n)

        def register(i):
            barrier.wait()
            _register_child_run("team-1", f"member-{i}")

        threads = [threading.Thread(target=register, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        ids = get_child_run_ids("team-1")
        assert len(ids) == n
        for i in range(n):
            assert f"member-{i}" in ids


# ============================================================================
# Unit tests: cancel_run cascade
# ============================================================================


class TestCancelRunCascade:
    """Tests for team._run.cancel_run cascade behaviour."""

    @patch("agno.team._run.cancel_run_global")
    def test_cancel_run_cascades_to_children(self, mock_cancel_global):
        """cancel_run should call cancel_run_global for team + all member runs."""
        from agno.team._run import cancel_run

        mock_cancel_global.return_value = True

        # Register some children
        _register_child_run("team-1", "member-1")
        _register_child_run("team-1", "member-2")

        result = cancel_run("team-1")

        assert result is True
        # Should have been called 3 times: team + 2 members
        assert mock_cancel_global.call_count == 3
        called_ids = {call.args[0] for call in mock_cancel_global.call_args_list}
        assert called_ids == {"team-1", "member-1", "member-2"}

    @patch("agno.team._run.cancel_run_global")
    def test_cancel_run_cleans_up_mapping(self, mock_cancel_global):
        """cancel_run should unregister the team run after cascading."""
        from agno.team._run import cancel_run

        mock_cancel_global.return_value = True
        _register_child_run("team-1", "member-1")

        cancel_run("team-1")

        assert get_child_run_ids("team-1") == set()

    @patch("agno.team._run.cancel_run_global")
    def test_cancel_run_no_children(self, mock_cancel_global):
        """cancel_run with no children should only cancel the team itself."""
        from agno.team._run import cancel_run

        mock_cancel_global.return_value = False

        result = cancel_run("team-no-children")

        assert result is False
        assert mock_cancel_global.call_count == 1

    @pytest.mark.asyncio
    @patch("agno.team._run.acancel_run_global")
    async def test_acancel_run_cascades_to_children(self, mock_acancel_global):
        """acancel_run should cascade to all member runs."""
        from agno.team._run import acancel_run

        mock_acancel_global.return_value = True

        _register_child_run("team-1", "member-1")
        _register_child_run("team-1", "member-2")

        result = await acancel_run("team-1")

        assert result is True
        assert mock_acancel_global.call_count == 3
        called_ids = {call.args[0] for call in mock_acancel_global.call_args_list}
        assert called_ids == {"team-1", "member-1", "member-2"}

    @pytest.mark.asyncio
    @patch("agno.team._run.acancel_run_global")
    async def test_acancel_run_cleans_up_mapping(self, mock_acancel_global):
        """acancel_run should unregister the team run after cascading."""
        from agno.team._run import acancel_run

        mock_acancel_global.return_value = True
        _register_child_run("team-1", "member-1")

        await acancel_run("team-1")

        assert get_child_run_ids("team-1") == set()
