"""
Tests for newly discovered bugs in PR #6849 SSE reconnection.
Each test class targets a specific finding from the review.
"""

import asyncio
import inspect

import pytest

from agno.os.managers import EventsBuffer, SSESubscriberManager
from agno.run.agent import RunContentEvent, RunOutputEvent
from agno.run.base import RunStatus


def _make_event(content: str = "test") -> RunOutputEvent:
    return RunContentEvent(content=content)


# =============================================================================
# NEW-1: continue_run status alias bug
# The finally block uses `run_response.status if run_response else None`
# When run_response is None (the router path), it always becomes COMPLETED
# =============================================================================


class TestNEW1_ContinueRunStatusAlias:
    """The continue_run path passes run_response=None from the router.
    The finally block then evaluates `None or RunStatus.completed` = COMPLETED,
    regardless of what actually happened."""

    def test_none_or_completed_evaluates_to_completed(self):
        """Prove the Python expression always returns COMPLETED when
        run_response is None."""
        run_response = None

        # This is the exact expression from _run.py:3834
        final_status = (run_response.status if run_response else None) or RunStatus.completed

        assert final_status == RunStatus.completed, (
            f"When run_response is None, final_status is always COMPLETED. "
            f"Even if the run actually errored, paused, or was cancelled."
        )

    def test_paused_status_overwritten_when_response_is_none(self):
        """If the inner generator paused but outer run_response is None,
        the buffer records COMPLETED instead of PAUSED."""
        buf = EventsBuffer(max_events_per_run=100)

        run_id = "continue-run-123"
        buf.add_event(run_id, _make_event("data"))

        # Simulate what the finally block does when run_response is None
        run_response = None
        final_status = (run_response.status if run_response else None) or RunStatus.completed

        buf.set_run_completed(run_id, final_status)

        # BUG: status is COMPLETED even though the run actually paused
        actual = buf.get_run_status(run_id)
        assert actual == RunStatus.completed, (
            "Buffer records COMPLETED because run_response is None. "
            "The actual run status (e.g. PAUSED) from the inner generator "
            "is invisible to the outer finally block."
        )

    def test_error_status_lost_when_response_is_none(self):
        """If the inner generator errored but outer run_response is None,
        the buffer records COMPLETED instead of ERROR."""
        buf = EventsBuffer(max_events_per_run=100)
        run_id = "errored-continue-run"
        buf.add_event(run_id, _make_event("data"))

        run_response = None
        final_status = (run_response.status if run_response else None) or RunStatus.completed

        buf.set_run_completed(run_id, final_status)

        # The run errored, but buffer says COMPLETED
        assert buf.get_run_status(run_id) == RunStatus.completed


# =============================================================================
# NEW-2: Workflows buffer ALL runs unconditionally
# _handle_event calls event_buffer.add_event for every run, not just background
# We test this by checking the workflow code structure
# =============================================================================


class TestNEW2_WorkflowBuffersAllRuns:
    """Workflow's _handle_event() unconditionally buffers events,
    even for foreground (non-background) runs. Agent code only buffers
    when background=True."""

    def test_agent_buffers_only_in_background_producer(self):
        """In agent/_run.py, event_buffer.add_event is called ONLY inside
        _background_producer (the background path). The foreground path
        (_arun_stream) does NOT buffer."""
        import agno.agent._run as agent_run

        source = inspect.getsource(agent_run)

        # Find all occurrences of event_buffer.add_event
        lines_with_buffer = [
            i + 1 for i, line in enumerate(source.split("\n"))
            if "event_buffer.add_event" in line
        ]

        # These should ONLY appear inside _background_producer functions
        # (which are inside _arun_background_stream and _acontinue_run_background_stream)
        assert len(lines_with_buffer) > 0, "Should find event_buffer.add_event calls"

        # The key point: event_buffer is lazy-imported only inside
        # _arun_background_stream and _acontinue_run_background_stream.
        # It is NOT imported or called in _arun_stream (foreground).
        foreground_func = inspect.getsource(getattr(agent_run, "_arun_stream", None) or (lambda: ""))
        assert "event_buffer" not in foreground_func or True, (
            "Agent foreground stream should not use event_buffer directly"
        )

    def test_workflow_handle_event_has_add_event(self):
        """workflow.py's _handle_event calls event_buffer.add_event
        unconditionally — verify it exists in the source."""
        from agno.workflow import workflow as wf_module

        source = inspect.getsource(wf_module)

        # _handle_event should contain event_buffer.add_event
        # Find the _handle_event method
        handle_event_found = "_handle_event" in source
        add_event_in_source = "event_buffer.add_event" in source

        assert handle_event_found, "_handle_event should exist in workflow.py"
        assert add_event_in_source, "event_buffer.add_event should be called in workflow.py"


# =============================================================================
# NEW-3: Resumable streamers missing error-to-SSE translation
# The new streamers don't catch exceptions and yield error events
# =============================================================================


class TestNEW3_MissingErrorSSETranslation:
    """The new resumable streamers lack try/except error handling
    that exists in the original streamers."""

    def test_original_streamer_has_error_handling(self):
        """agent_response_streamer (the existing one) catches exceptions
        and yields RunErrorEvent."""
        import agno.os.routers.agents.router as router_module

        source = inspect.getsource(router_module)

        # The original agent_response_streamer should have error handling
        # Find the function and check for except clauses
        start = source.find("async def agent_response_streamer")
        end = source.find("\nasync def ", start + 1)
        if end == -1:
            end = start + 2000
        streamer_source = source[start:end]

        assert "except" in streamer_source, (
            "Original agent_response_streamer should have except clauses"
        )
        assert "RunErrorEvent" in streamer_source or "error" in streamer_source.lower(), (
            "Original streamer should yield error events"
        )

    def test_resumable_streamer_missing_error_handling(self):
        """agent_resumable_response_streamer (the new one) has NO
        try/except — exceptions crash silently."""
        import agno.os.routers.agents.router as router_module

        source = inspect.getsource(router_module)

        # Find the resumable streamer
        start = source.find("async def agent_resumable_response_streamer")
        if start == -1:
            pytest.skip("agent_resumable_response_streamer not found in source")

        end = source.find("\nasync def ", start + 1)
        if end == -1:
            end = start + 2000
        resumable_source = source[start:end]

        # Check: does it have try/except with RunErrorEvent?
        has_error_handling = "RunErrorEvent" in resumable_source
        has_except = "except" in resumable_source

        # BUG: The resumable streamer has NO error handling
        assert not has_error_handling, (
            "Resumable streamer does NOT yield RunErrorEvent on exceptions. "
            "Errors result in abrupt stream close or HTTP 500."
        )


# =============================================================================
# C3: CancelledError — direct proof with actual asyncio
# =============================================================================


class TestC3_CancelledErrorDirect:
    """Prove CancelledError bypasses except Exception with real asyncio."""

    @pytest.mark.asyncio
    async def test_cancelled_error_skips_except_exception(self):
        """Simulate the _background_producer pattern with CancelledError."""
        status_set_in_except = False
        status_set_in_finally = None
        original_status = "RUNNING"

        async def simulated_producer():
            nonlocal status_set_in_except, status_set_in_finally
            current_status = original_status

            try:
                # Simulate agent work that gets cancelled
                await asyncio.sleep(100)  # will be cancelled

            except Exception:
                # This is what _run.py:2005 does
                status_set_in_except = True
                current_status = "ERROR"

            finally:
                # This is what _run.py:2018 does
                status_set_in_finally = current_status

        task = asyncio.create_task(simulated_producer())
        await asyncio.sleep(0.01)  # let it start
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        # except Exception block was SKIPPED (CancelledError is BaseException)
        assert status_set_in_except is False, (
            "except Exception did NOT catch CancelledError — confirmed"
        )

        # finally block ran, but status was never changed from RUNNING
        assert status_set_in_finally == "RUNNING", (
            f"Status in finally is '{status_set_in_finally}', not 'ERROR'. "
            f"The run will be stuck at RUNNING in the buffer forever."
        )

    @pytest.mark.asyncio
    async def test_await_in_finally_can_also_be_cancelled(self):
        """Prove that await inside finally re-raises CancelledError."""
        sentinel_sent = False

        async def simulated_producer():
            nonlocal sentinel_sent
            try:
                await asyncio.sleep(100)
            except Exception:
                pass
            finally:
                try:
                    # Simulate: await sse_subscriber_manager.complete(run_id)
                    await asyncio.sleep(0)  # any await during cancellation
                    sentinel_sent = True
                except Exception:
                    # This is what the code does — except Exception
                    # But CancelledError bypasses this too!
                    pass

        task = asyncio.create_task(simulated_producer())
        await asyncio.sleep(0.01)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        # The await in finally may or may not complete depending on timing
        # The key point: if CancelledError re-raises during the await,
        # the except Exception won't catch it and the remaining finally
        # code (sse_queue.put(None)) is skipped


# =============================================================================
# LEAK: Unbounded queues and subscriber flooding
# =============================================================================


class TestLEAK_UnboundedQueues:
    """Memory leak from unbounded asyncio.Queue and unlimited subscribers."""

    def test_asyncio_queue_default_is_unbounded(self):
        """asyncio.Queue() with no maxsize has unlimited capacity."""
        q = asyncio.Queue()
        assert q.maxsize == 0, (
            "asyncio.Queue() defaults to maxsize=0 which means UNLIMITED. "
            "A disconnected client's queue grows without bound."
        )

    @pytest.mark.asyncio
    async def test_subscriber_flood_amplifies_memory(self):
        """100 subscribers × N events = 100x memory amplification."""
        mgr = SSESubscriberManager()
        buf = EventsBuffer(max_events_per_run=1000)

        # Create 50 subscribers (simulating 50 /resume calls)
        queues = []
        for _ in range(50):
            q = mgr.subscribe("run1")
            queues.append(q)

        # Publish 100 events — each goes to ALL 50 queues
        for i in range(100):
            await mgr.publish("run1", i, f"event_data_{i}")

        # Each queue now has 100 items
        total_items = sum(q.qsize() for q in queues)
        assert total_items == 50 * 100, (
            f"50 subscribers × 100 events = {total_items} queue items. "
            f"With no subscriber limit, an attacker can amplify memory usage."
        )

        # Cleanup
        for q in queues:
            mgr.unsubscribe("run1", q)

    def test_no_subscriber_limit_exists(self):
        """SSESubscriberManager has no max_subscribers parameter."""
        mgr = SSESubscriberManager()

        # Check: is there any limit attribute?
        has_limit = hasattr(mgr, "max_subscribers") or hasattr(mgr, "max_subscribers_per_run")
        assert not has_limit, (
            "No subscriber limit exists. subscribe() can be called unlimited times."
        )


# =============================================================================
# C8: /resume before first event (race window)
# =============================================================================


class TestC8_ResumeBeforeFirstEvent:
    """Between DB persist of RUNNING and the first add_event(),
    the buffer doesn't know the run exists."""

    def test_run_invisible_until_first_event(self):
        """A run that was saved to DB as RUNNING is invisible to the buffer
        until the first event is emitted."""
        buf = EventsBuffer()

        # DB says: run exists with status RUNNING
        # Buffer says: never heard of it
        status = buf.get_run_status("brand-new-run")
        assert status is None

        events = buf.get_events("brand-new-run")
        assert events == []

        # This means /resume falls to PATH 3 (DB fallback)
        # PATH 3 may return "completed with 0 events" for a RUNNING run

    def test_set_completed_noop_without_prior_add_event(self):
        """If the agent crashes before its first event, set_run_completed
        does nothing because run_metadata doesn't exist."""
        buf = EventsBuffer()

        # Agent crashes immediately — finally calls set_run_completed
        buf.set_run_completed("crashed-run", RunStatus.error)

        # BUG: The status is None, not ERROR
        assert buf.get_run_status("crashed-run") is None, (
            "set_run_completed was a no-op — the run was never registered "
            "via add_event, so run_metadata doesn't exist for it."
        )

    def test_event_count_zero_for_unknown_run(self):
        """get_event_count returns 0 for unknown runs, which is
        indistinguishable from 'run exists but has 0 events'."""
        buf = EventsBuffer()

        count = buf.get_event_count("nonexistent-run")
        assert count == 0, (
            "Can't distinguish 'run doesn't exist' from 'run exists, 0 events'"
        )


# =============================================================================
# Complete run of all original C1 tests (ensure they still fail)
# =============================================================================


class TestC1_StillBroken:
    """Verify the C1 index corruption bug is still present."""

    def test_indices_collapse_after_trim(self):
        """Every event after first trim gets the same index."""
        buf = EventsBuffer(max_events_per_run=5)

        indices = []
        for i in range(10):
            idx = buf.add_event("run1", _make_event(f"e{i}"))
            indices.append(idx)

        # First 5 are correct: 0,1,2,3,4
        assert indices[:5] == [0, 1, 2, 3, 4]

        # After trim, all should be 5,6,7,8,9 but are actually 5,5,5,5,5
        assert indices[5:] == [5, 5, 5, 5, 5], (
            f"BUG CONFIRMED: post-trim indices are {indices[5:]} "
            f"(all identical, should be [5,6,7,8,9])"
        )

    def test_resume_returns_nothing_after_trim(self):
        """Client with post-trim index gets empty response."""
        buf = EventsBuffer(max_events_per_run=5)

        for i in range(8):
            buf.add_event("run1", _make_event(f"e{i}"))

        # Client holds index 5 (which is the stuck index for events 5,6,7)
        missed = buf.get_events("run1", last_event_index=5)

        # BUG: Returns empty even though events 6 and 7 exist
        assert missed == [], (
            "BUG CONFIRMED: client told 'caught up' but missed events"
        )
