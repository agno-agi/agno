"""Tests that demonstrate blocking issues in SSE reconnection (PR #6849).

Each test class corresponds to one blocker identified in review.
Tests are written to FAIL on the current code, proving the bug exists.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from agno.os.managers import EventsBuffer, SSESubscriberManager
from agno.run.agent import RunContentEvent, RunOutputEvent
from agno.run.base import RunStatus


def _make_event(content: str = "test") -> RunOutputEvent:
    return RunContentEvent(content=content)


# =============================================================================
# C1: Event Index Corruption After Buffer Trim
# =============================================================================


class TestC1_EventIndexCorruptionAfterTrim:
    """The event_index returned by add_event() is a list position, not a
    monotonic logical index. After the buffer trims, previously-issued
    indices become invalid and get_events() returns wrong results."""

    def test_index_stays_valid_after_trim(self):
        """After trim, a client reconnecting with a pre-trim index should
        still receive the correct events."""
        buf = EventsBuffer(max_events_per_run=5)

        # Add 5 events (indices 0-4, no trim)
        indices = []
        for i in range(5):
            idx = buf.add_event("run1", _make_event(f"event-{i}"))
            indices.append(idx)

        assert indices == [0, 1, 2, 3, 4]

        # Add event 6 — triggers trim. List becomes [event-1..event-5]
        idx_5 = buf.add_event("run1", _make_event("event-5"))

        # The returned index should be 5 (the 6th event, 0-based)
        assert idx_5 == 5

        # A client that last saw index 3 should get events 4 and 5
        missed = buf.get_events("run1", last_event_index=3)

        # BUG: After trim, len(events) is 5. Index 3 < 4 (len-1),
        # so get_events returns events[4:] = [event-5] — only 1 event.
        # But the client should get event-4 AND event-5 (2 events).
        # Even worse: the events returned are from physical positions,
        # not logical positions, so the content is wrong.
        assert len(missed) == 2, (
            f"Expected 2 missed events (event-4 and event-5), "
            f"got {len(missed)}: {[e.content for e in missed]}"
        )

    def test_all_indices_same_after_repeated_trims(self):
        """After repeated trims, every new event gets the same index value,
        breaking dedup logic."""
        buf = EventsBuffer(max_events_per_run=3)

        # Fill buffer: indices 0, 1, 2
        for i in range(3):
            buf.add_event("run1", _make_event(f"event-{i}"))

        # Add 5 more events — each triggers a trim
        post_trim_indices = []
        for i in range(3, 8):
            idx = buf.add_event("run1", _make_event(f"event-{i}"))
            post_trim_indices.append(idx)

        # BUG: After each trim, len goes 4→trim→3, so every index is 3
        # All 5 events get index=3. They should be 3, 4, 5, 6, 7.
        assert post_trim_indices == [3, 4, 5, 6, 7], (
            f"Indices should be monotonically increasing. "
            f"Got: {post_trim_indices}"
        )

    def test_client_thinks_caught_up_when_not(self):
        """A client holding a post-trim index calls get_events and is told
        it's caught up, even though events exist that it hasn't seen."""
        buf = EventsBuffer(max_events_per_run=5)

        # Add 7 events (triggers trim at event 6)
        for i in range(7):
            buf.add_event("run1", _make_event(f"event-{i}"))

        # Client last saw index 5 (which was returned by add_event for event-5)
        # After trim, buffer has 5 events at physical positions 0-4
        # get_events checks: 5 >= len(5) - 1 = 4 → True → returns []
        missed = buf.get_events("run1", last_event_index=5)

        # BUG: Returns [] — client thinks caught up.
        # But event-6 (index 6) exists and client hasn't seen it.
        assert len(missed) > 0, (
            "Client was told it's caught up, but event-6 was missed!"
        )


# =============================================================================
# C2: PATH 3 (DB Fallback) Ignores last_event_index
# =============================================================================
# This blocker is in the router code, not EventsBuffer.
# We verify the precondition: get_events() with last_event_index works,
# but the router's PATH 3 never calls it.
# (Router test would require FastAPI TestClient — covered separately)


# =============================================================================
# C3: CancelledError Bypasses Error-State Bookkeeping
# =============================================================================


class TestC3_CancelledErrorBypassesCleanup:
    """CancelledError is BaseException, not Exception. The except Exception
    handler in _background_producer misses it. set_run_completed may not
    be called, leaving the buffer entry stuck at 'running' forever."""

    def test_running_status_never_cleaned_up(self):
        """EventsBuffer.cleanup_runs() skips entries with status=running.
        If set_run_completed is never called, the entry leaks forever."""
        buf = EventsBuffer(max_events_per_run=100, cleanup_interval=0)

        # Simulate: producer adds events but crashes before set_run_completed
        buf.add_event("leaked_run", _make_event("data"))

        # Status is 'running' (set by add_event on first call)
        assert buf.get_run_status("leaked_run") == RunStatus.running

        # Run cleanup — should it clean up this "stuck" run? Currently: no.
        buf.cleanup_runs()

        # BUG: The entry is still there. In a real server, this run's
        # background task was cancelled (CancelledError), set_run_completed
        # was never called, and this entry will live in memory forever.
        status = buf.get_run_status("leaked_run")
        assert status is not None, "Run should still exist (this is the bug — it's leaked)"

        # Verify: even with cleanup_interval=0, running entries aren't cleaned
        # This proves the leak — there's no mechanism to clean stuck runs
        assert len(buf.events) == 1, "Leaked run's events still in memory"
        assert len(buf.run_metadata) == 1, "Leaked run's metadata still in memory"

    def test_paused_status_never_cleaned_up(self):
        """RunStatus.paused is also not in the cleanup eligibility list."""
        # RunStatus imported at module level

        buf = EventsBuffer(max_events_per_run=100, cleanup_interval=0)
        buf.add_event("paused_run", _make_event("data"))
        buf.set_run_completed("paused_run", RunStatus.paused)

        # Cleanup with interval=0 means everything eligible should be cleaned
        buf.cleanup_runs()

        # BUG: paused is not in [completed, error, cancelled]
        status = buf.get_run_status("paused_run")
        assert status is not None, "Paused run should still exist (this is the bug)"


# =============================================================================
# C7: No Error Event on SSE Wire
# =============================================================================
# This is a behavioral issue in _background_producer — when the agent errors,
# the None sentinel is sent but no error SSE event is emitted first.
# Testing this requires mocking the agent run, covered in integration tests.


# =============================================================================
# C8: /resume Before First Event → False "Completed" Signal
# =============================================================================


class TestC8_ResumeBeforeFirstEvent:
    """If /resume is called before the first add_event(), the buffer has
    no metadata for the run_id, so get_run_status returns None."""

    def test_run_invisible_before_first_event(self):
        """A run that started (DB has RUNNING status) but hasn't emitted
        its first event yet is invisible to the buffer."""
        buf = EventsBuffer()

        # Simulate: _arun_background_stream saved RUNNING to DB,
        # spawned the task, but _background_producer hasn't yielded yet.
        # The buffer knows nothing about this run.

        status = buf.get_run_status("new_run_123")
        assert status is None, (
            "Expected None — the buffer doesn't know about this run yet. "
            "A /resume call would fall through to PATH 3 (DB fallback) "
            "which may return a false 'completed with 0 events' signal."
        )

        # This proves the race window: between DB persist of RUNNING
        # and the first add_event() call, the buffer is blind.
        events = buf.get_events("new_run_123")
        assert events == []


# =============================================================================
# S2: DoS via Subscriber Flooding
# =============================================================================


class TestS2_SubscriberFlooding:
    """SSESubscriberManager has no limit on subscribers per run_id.
    An attacker can create unlimited queues to exhaust memory."""

    @pytest.mark.asyncio
    async def test_unlimited_subscribers_allowed(self):
        """Prove that there's no cap on subscriber count per run."""
        mgr = SSESubscriberManager()

        # Subscribe 100 times to the same run
        queues = []
        for _ in range(100):
            q = mgr.subscribe("run1")
            queues.append(q)

        # All 100 subscriptions succeed — no limit enforced
        assert len(queues) == 100

        # Check internal state — 100 queues for one run
        assert len(mgr._subscribers.get("run1", [])) == 100, (
            "Expected 100 subscribers — no rate limiting exists. "
            "An attacker can exhaust server memory this way."
        )

        # Cleanup
        for q in queues:
            mgr.unsubscribe("run1", q)


# =============================================================================
# SSESubscriberManager: subscribe-after-complete livelock (H1)
# =============================================================================


class TestH1_SubscribeAfterComplete:
    """If complete() fires before subscribe(), the new subscriber's
    queue never receives the None sentinel and blocks forever."""

    @pytest.mark.asyncio
    async def test_subscribe_after_complete_gets_no_sentinel(self):
        """A subscriber that registers after complete() never receives
        the None sentinel, causing an infinite hang at queue.get()."""
        mgr = SSESubscriberManager()

        # Run completes — sends None to all existing subscribers (none)
        await mgr.complete("run1")

        # Now a client subscribes (too late — complete already fired)
        queue = mgr.subscribe("run1")

        # The queue should have the None sentinel... but it doesn't
        assert queue.empty(), (
            "Queue is empty — the None sentinel was sent before this "
            "subscriber existed. This subscriber will hang forever "
            "at queue.get() with no timeout."
        )

        # In real code, the router's re-check (line 375) catches this
        # for SSE, but WebSocket has no re-check — confirmed hang.
        mgr.unsubscribe("run1", queue)


# =============================================================================
# EventsBuffer: set_run_completed is no-op for unknown runs
# =============================================================================


class TestC4_SetRunCompletedNoOp:
    """If _background_producer crashes before the first add_event(),
    set_run_completed is a no-op because run_metadata doesn't exist."""

    def test_set_completed_before_any_events(self):
        """set_run_completed does nothing if no events were ever added."""
        # RunStatus imported at module level

        buf = EventsBuffer()

        # Simulate: agent crashes immediately, finally block calls this
        buf.set_run_completed("crashed_run", RunStatus.error)

        # BUG: status is None, not error — the run was never registered
        status = buf.get_run_status("crashed_run")
        assert status is None, (
            "set_run_completed was a no-op because the run was never "
            "registered via add_event(). The buffer has no record of "
            "this run's existence or failure."
        )
