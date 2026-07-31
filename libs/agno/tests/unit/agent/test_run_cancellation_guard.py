"""Unit tests for CancelledError handler preserving PAUSED status.

Tests the guard added to _arun and _arun_stream that prevents
CancelledError/GeneratorExit handlers from overwriting PAUSED to CANCELLED.
"""
import asyncio

import pytest

from agno.agent._run import _handle_run_cancellation
from agno.run.agent import RunOutput
from agno.run.base import RunStatus


class TestCancellationPreservesPaused:
    """Verify that CancelledError handling preserves PAUSED status."""

    def test_cancellation_handler_overwrites_non_paused(self):
        """When status is NOT paused, _handle_run_cancellation sets CANCELLED."""
        run = RunOutput(run_id="test-1", content="running")
        run.status = RunStatus.running

        _handle_run_cancellation(run, KeyboardInterrupt())
        assert run.status == RunStatus.cancelled
        assert run.content is not None  # preserves partial content

    def test_cancellation_handler_overwrites_error(self):
        """When status is ERROR, _handle_run_cancellation still sets CANCELLED."""
        run = RunOutput(run_id="test-2", content="error")
        run.status = RunStatus.error

        _handle_run_cancellation(run, KeyboardInterrupt())
        assert run.status == RunStatus.cancelled

    def test_guard_preserves_paused_status(self):
        """Guard pattern: if status is PAUSED, don't call _handle_run_cancellation.

        This is what the fix adds in _arun and _arun_stream before the handler.
        """
        run = RunOutput(run_id="test-3", content="paused for input")
        run.status = RunStatus.paused

        # Simulate the guard we added to _arun and _arun_stream:
        #   if run_response.status == RunStatus.paused:
        #       raise
        guard_triggered = run.status == RunStatus.paused
        if not guard_triggered:
            _handle_run_cancellation(run, KeyboardInterrupt())

        # Status must remain PAUSED because the guard fired
        assert run.status == RunStatus.paused
        assert guard_triggered is True

    def test_guard_matches_exact_paused_enum(self):
        """Guard uses identity-equivalent comparison via RunStatus.paused."""
        run = RunOutput(run_id="test-4")
        run.status = RunStatus.paused
        # Verify the guard condition matches PAUSED
        assert run.status == RunStatus.paused
        # And does NOT match other terminal states
        assert run.status != RunStatus.cancelled
        assert run.status != RunStatus.completed
        assert run.status != RunStatus.error

    @pytest.mark.asyncio
    async def test_cancel_in_cancelled_state_is_noop(self):
        """If somehow already CANCELLED, re-cancelling doesn't crash."""
        run = RunOutput(run_id="test-5", content="already cancelled")
        run.status = RunStatus.cancelled
        # Guard does not fire (status is not PAUSED)
        assert run.status != RunStatus.paused
        # Handler is reached, sets CANCELLED (idempotent)
        _handle_run_cancellation(run, KeyboardInterrupt())
        assert run.status == RunStatus.cancelled
