"""Unit tests for background execution feature."""

import asyncio
import inspect
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

from agno.agent import _init, _response, _run, _storage
from agno.agent.agent import Agent
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.cancel import (
    cancel_run,
    cleanup_run,
    get_active_runs,
    get_cancellation_manager,
    is_cancelled,
    register_run,
    set_cancellation_manager,
)
from agno.run.cancellation_management.in_memory_cancellation_manager import InMemoryRunCancellationManager
from agno.session import AgentSession


@pytest.fixture(autouse=True)
def reset_cancellation_manager():
    original_manager = get_cancellation_manager()
    set_cancellation_manager(InMemoryRunCancellationManager())
    try:
        yield
    finally:
        set_cancellation_manager(original_manager)


def _patch_sync_dispatch_dependencies(
    agent: Agent,
    monkeypatch: pytest.MonkeyPatch,
    runs: Optional[list[Any]] = None,
) -> None:
    monkeypatch.setattr(_init, "has_async_db", lambda agent: False)
    monkeypatch.setattr(_storage, "update_metadata", lambda agent, session=None: None)
    monkeypatch.setattr(_storage, "load_session_state", lambda agent, session=None, session_state=None: session_state)
    monkeypatch.setattr(_run, "resolve_run_dependencies", lambda agent, run_context: None)
    monkeypatch.setattr(_response, "get_response_format", lambda agent, run_context=None: None)
    monkeypatch.setattr(
        _storage,
        "read_or_create_session",
        lambda agent, session_id=None, user_id=None: AgentSession(session_id=session_id, user_id=user_id, runs=runs),
    )


# ============= Cancel-before-start semantics =============


class TestCancelBeforeStart:
    def test_cancel_before_register_preserves_intent(self):
        """Cancelling a run before it's registered stores the intent."""
        run_id = "future-run"
        # Cancel before registering
        was_registered = cancel_run(run_id)
        assert was_registered is False

        # Register the run — should NOT overwrite the cancel intent
        register_run(run_id)

        # The run should still be cancelled
        assert is_cancelled(run_id) is True

    def test_cancel_after_register_marks_cancelled(self):
        """Cancelling a run after registration works normally."""
        run_id = "registered-run"
        register_run(run_id)
        assert is_cancelled(run_id) is False

        was_registered = cancel_run(run_id)
        assert was_registered is True
        assert is_cancelled(run_id) is True

    def test_register_does_not_overwrite_cancel(self):
        """Calling register_run on an already-cancelled run preserves the cancel state."""
        run_id = "cancel-then-register"
        cancel_run(run_id)
        register_run(run_id)
        register_run(run_id)  # Call again to be sure

        assert is_cancelled(run_id) is True

    def test_cleanup_removes_cancel_intent(self):
        """Cleanup removes the run from tracking entirely."""
        run_id = "cleanup-test"
        cancel_run(run_id)
        assert run_id in get_active_runs()

        cleanup_run(run_id)
        assert run_id not in get_active_runs()


# ============= Background execution validation =============


class TestBackgroundValidation:
    def test_background_with_stream_requires_db(self, monkeypatch: pytest.MonkeyPatch):
        """Background execution with streaming requires a database."""
        agent = Agent(name="test-agent")
        agent.db = None
        _patch_sync_dispatch_dependencies(agent, monkeypatch, runs=[])

        with pytest.raises(ValueError, match="Background execution requires a database"):
            _run.arun_dispatch(agent=agent, input="hello", stream=True, background=True)

    def test_background_without_db_raises_value_error(self, monkeypatch: pytest.MonkeyPatch):
        """Background execution requires a database."""
        agent = Agent(name="test-agent")
        agent.db = None
        _patch_sync_dispatch_dependencies(agent, monkeypatch, runs=[])

        with pytest.raises(ValueError, match="Background execution requires a database"):
            _run.arun_dispatch(agent=agent, input="hello", stream=False, background=True)

    def test_background_dispatch_returns_coroutine(self, monkeypatch: pytest.MonkeyPatch):
        """arun_dispatch with background=True returns a coroutine (not async def itself)."""
        agent = Agent(name="test-agent")
        agent.db = MagicMock()
        _patch_sync_dispatch_dependencies(agent, monkeypatch, runs=[])

        result = _run.arun_dispatch(agent=agent, input="hello", stream=False, background=True)
        # arun_dispatch is not async, so it returns a coroutine object
        assert inspect.iscoroutine(result)
        # Clean up the coroutine to avoid warnings
        result.close()


# ============= Background execution lifecycle =============


class TestBackgroundLifecycle:
    @pytest.mark.asyncio
    async def test_arun_background_returns_pending_status(self, monkeypatch: pytest.MonkeyPatch):
        """_arun_background returns immediately with PENDING status."""
        agent = Agent(name="test-agent")

        saved_sessions: list[AgentSession] = []

        async def fake_aread_or_create_session(agent, session_id=None, user_id=None):
            return AgentSession(session_id=session_id or "test-session", user_id=user_id, runs=[])

        async def fake_asave_session(agent, session=None):
            saved_sessions.append(session)

        async def fake_arun(agent, run_response, run_context, **kwargs):
            # Simulate successful completion
            run_response.status = RunStatus.completed
            run_response.content = "done"
            return run_response

        monkeypatch.setattr(_storage, "aread_or_create_session", fake_aread_or_create_session)
        monkeypatch.setattr(_storage, "update_metadata", lambda agent, session=None: None)
        monkeypatch.setattr("agno.agent._session.asave_session", fake_asave_session)
        monkeypatch.setattr(_run, "_arun", fake_arun)

        run_response = RunOutput(
            run_id="bg-run-1",
            session_id="test-session",
        )
        run_context = RunContext(
            run_id="bg-run-1",
            session_id="test-session",
        )

        result = await _run._arun_background(
            agent,
            run_response=run_response,
            run_context=run_context,
            session_id="test-session",
        )

        # Should return immediately with PENDING status
        assert result.status == RunStatus.pending
        assert result.run_id == "bg-run-1"

        # Wait a moment for the background task to complete
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_arun_background_persists_pending_before_returning(self, monkeypatch: pytest.MonkeyPatch):
        """Background run persists PENDING status to DB before returning."""
        agent = Agent(name="test-agent")

        persisted_statuses: list[RunStatus] = []

        async def fake_aread_or_create_session(agent, session_id=None, user_id=None):
            return AgentSession(session_id=session_id or "test-session", user_id=user_id, runs=[])

        async def fake_asave_session(agent, session=None):
            if session and session.runs:
                for run in session.runs:
                    persisted_statuses.append(run.status)

        async def fake_asave_run(agent, run=None, session_id=None, user_id=None, run_index=None):
            if run is not None:
                persisted_statuses.append(run.status)

        async def fake_arun(agent, run_response, run_context, **kwargs):
            run_response.status = RunStatus.completed
            return run_response

        monkeypatch.setattr(_storage, "aread_or_create_session", fake_aread_or_create_session)
        monkeypatch.setattr(_storage, "update_metadata", lambda agent, session=None: None)
        monkeypatch.setattr("agno.agent._session.asave_session", fake_asave_session)
        monkeypatch.setattr("agno.agent._session.asave_run", fake_asave_run)
        monkeypatch.setattr(_run, "_arun", fake_arun)

        run_response = RunOutput(run_id="bg-run-2", session_id="test-session")
        run_context = RunContext(run_id="bg-run-2", session_id="test-session")

        await _run._arun_background(
            agent,
            run_response=run_response,
            run_context=run_context,
            session_id="test-session",
        )

        # First save should be with PENDING status (before returning)
        assert RunStatus.pending in persisted_statuses

        # Wait for background task
        await asyncio.sleep(0.1)

        # Background task should have saved RUNNING (via asave_run after the transition)
        assert RunStatus.running in persisted_statuses

    @pytest.mark.asyncio
    async def test_arun_background_error_persists_error_status(self, monkeypatch: pytest.MonkeyPatch):
        """If the background run fails, ERROR status is persisted."""
        agent = Agent(name="test-agent")

        final_statuses: list[RunStatus] = []

        async def fake_aread_or_create_session(agent, session_id=None, user_id=None):
            return AgentSession(session_id=session_id or "test-session", user_id=user_id, runs=[])

        async def fake_asave_session(agent, session=None):
            if session and session.runs:
                for run in session.runs:
                    final_statuses.append(run.status)

        async def fake_asave_run(agent, run=None, session_id=None, user_id=None, run_index=None):
            if run is not None:
                final_statuses.append(run.status)

        async def fake_arun_that_fails(agent, run_response, run_context, **kwargs):
            raise RuntimeError("model call failed")

        monkeypatch.setattr(_storage, "aread_or_create_session", fake_aread_or_create_session)
        monkeypatch.setattr(_storage, "update_metadata", lambda agent, session=None: None)
        monkeypatch.setattr("agno.agent._session.asave_session", fake_asave_session)
        monkeypatch.setattr("agno.agent._session.asave_run", fake_asave_run)
        monkeypatch.setattr(_run, "_arun", fake_arun_that_fails)

        run_response = RunOutput(run_id="bg-run-err", session_id="test-session")
        run_context = RunContext(run_id="bg-run-err", session_id="test-session")

        result = await _run._arun_background(
            agent,
            run_response=run_response,
            run_context=run_context,
            session_id="test-session",
        )

        assert result.status == RunStatus.pending

        # Wait for background task to complete (and fail)
        await asyncio.sleep(0.2)

        # Should have persisted ERROR status (via asave_run on error transition)
        assert RunStatus.error in final_statuses


class TestBackgroundConcurrencyLimit:
    @pytest.mark.asyncio
    async def test_second_run_waits_as_pending_under_limit(self, monkeypatch: pytest.MonkeyPatch):
        """With a concurrency limit of 1, a second background run stays PENDING
        (never transitions to RUNNING) until the first run finishes."""
        from agno.run import concurrency
        from agno.run.concurrency import set_background_max_concurrency

        set_background_max_concurrency(1)
        concurrency._semaphores.clear()
        try:
            agent = Agent(name="test-agent")

            first_started = asyncio.Event()
            release_first = asyncio.Event()
            running_order: list[str] = []

            async def fake_aread_or_create_session(agent, session_id=None, user_id=None):
                return AgentSession(session_id=session_id or "test-session", user_id=user_id, runs=[])

            async def fake_asave_session(agent, session=None):
                pass

            async def fake_arun(agent, run_response, run_context, **kwargs):
                running_order.append(run_response.run_id)
                if run_response.run_id == "bg-slot-1":
                    first_started.set()
                    await release_first.wait()
                run_response.status = RunStatus.completed
                return run_response

            monkeypatch.setattr(_storage, "aread_or_create_session", fake_aread_or_create_session)
            monkeypatch.setattr(_storage, "update_metadata", lambda agent, session=None: None)
            monkeypatch.setattr("agno.agent._session.asave_session", fake_asave_session)
            monkeypatch.setattr(_run, "_arun", fake_arun)

            first = await _run._arun_background(
                agent,
                run_response=RunOutput(run_id="bg-slot-1", session_id="test-session"),
                run_context=RunContext(run_id="bg-slot-1", session_id="test-session"),
                session_id="test-session",
            )
            second = await _run._arun_background(
                agent,
                run_response=RunOutput(run_id="bg-slot-2", session_id="test-session"),
                run_context=RunContext(run_id="bg-slot-2", session_id="test-session"),
                session_id="test-session",
            )

            await asyncio.wait_for(first_started.wait(), timeout=2)
            # Give the second task a chance to (incorrectly) start executing
            await asyncio.sleep(0.05)

            # Second run must be waiting for a slot: still PENDING, not yet executed
            assert running_order == ["bg-slot-1"]
            assert second.status == RunStatus.pending

            # Release the first run; the second should now execute and complete
            release_first.set()
            await asyncio.sleep(0.1)
            assert running_order == ["bg-slot-1", "bg-slot-2"]
            assert first.status == RunStatus.completed
            assert second.status == RunStatus.completed
        finally:
            set_background_max_concurrency(None)
            concurrency._semaphores.clear()

    @pytest.mark.asyncio
    async def test_cancel_while_waiting_for_slot_persists_cancelled(self, monkeypatch: pytest.MonkeyPatch):
        """A background run cancelled while queued behind the concurrency limit
        persists CANCELLED and never executes."""
        from agno.run import concurrency
        from agno.run.cancel import acancel_run
        from agno.run.concurrency import set_background_max_concurrency

        set_background_max_concurrency(1)
        concurrency._semaphores.clear()
        try:
            agent = Agent(name="test-agent")

            first_started = asyncio.Event()
            release_first = asyncio.Event()
            executed_run_ids: list[str] = []
            persisted_by_run: dict[str, list[RunStatus]] = {}

            async def fake_aread_or_create_session(agent, session_id=None, user_id=None):
                return AgentSession(session_id=session_id or "test-session", user_id=user_id, runs=[])

            async def fake_asave_session(agent, session=None):
                if session and session.runs:
                    for run in session.runs:
                        persisted_by_run.setdefault(run.run_id, []).append(run.status)

            async def fake_arun(agent, run_response, run_context, **kwargs):
                executed_run_ids.append(run_response.run_id)
                if run_response.run_id == "bg-cancel-holder":
                    first_started.set()
                    await release_first.wait()
                run_response.status = RunStatus.completed
                return run_response

            monkeypatch.setattr(_storage, "aread_or_create_session", fake_aread_or_create_session)
            monkeypatch.setattr(_storage, "update_metadata", lambda agent, session=None: None)
            monkeypatch.setattr("agno.agent._session.asave_session", fake_asave_session)
            monkeypatch.setattr(_run, "_arun", fake_arun)

            await _run._arun_background(
                agent,
                run_response=RunOutput(run_id="bg-cancel-holder", session_id="s1"),
                run_context=RunContext(run_id="bg-cancel-holder", session_id="s1"),
                session_id="s1",
            )
            queued = await _run._arun_background(
                agent,
                run_response=RunOutput(run_id="bg-cancel-queued", session_id="s2"),
                run_context=RunContext(run_id="bg-cancel-queued", session_id="s2"),
                session_id="s2",
            )

            await asyncio.wait_for(first_started.wait(), timeout=2)
            await asyncio.sleep(0.05)
            assert queued.status == RunStatus.pending

            # Cancel the queued run while it waits for a slot
            await acancel_run("bg-cancel-queued")

            # Wait for the cancellation poll to pick it up (poll interval 0.5s)
            for _ in range(40):
                await asyncio.sleep(0.05)
                if RunStatus.cancelled in persisted_by_run.get("bg-cancel-queued", []):
                    break

            assert queued.status == RunStatus.cancelled
            assert RunStatus.cancelled in persisted_by_run["bg-cancel-queued"]
            # The queued run never executed and never went RUNNING
            assert "bg-cancel-queued" not in executed_run_ids
            assert RunStatus.running not in persisted_by_run["bg-cancel-queued"]

            # The slot holder is unaffected
            release_first.set()
            await asyncio.sleep(0.1)
            assert "bg-cancel-holder" in executed_run_ids
        finally:
            set_background_max_concurrency(None)
            concurrency._semaphores.clear()


class TestBackgroundStreamConcurrencyLimit:
    @pytest.fixture(autouse=True)
    def _limiter(self):
        from agno.run import concurrency
        from agno.run.concurrency import set_background_max_concurrency

        set_background_max_concurrency(1)
        concurrency._semaphores.clear()
        try:
            yield
        finally:
            set_background_max_concurrency(None)
            concurrency._semaphores.clear()

    def _patch_stream_deps(self, monkeypatch, stream_started, release_stream):
        async def fake_aread_or_create_session(agent, session_id=None, user_id=None):
            return AgentSession(session_id=session_id or "test-session", user_id=None, runs=[])

        async def fake_asave_session(agent, session=None):
            pass

        async def fake_arun_stream(agent, run_response, run_context, **kwargs):
            stream_started.set()
            await release_stream.wait()
            run_response.status = RunStatus.completed
            from agno.run.agent import RunContentEvent

            yield RunContentEvent(content="hello", run_id=run_response.run_id)

        monkeypatch.setattr(_storage, "aread_or_create_session", fake_aread_or_create_session)
        monkeypatch.setattr(_storage, "update_metadata", lambda agent, session=None: None)
        monkeypatch.setattr("agno.agent._session.asave_session", fake_asave_session)
        monkeypatch.setattr(_run, "_arun_stream", fake_arun_stream)

    @pytest.mark.asyncio
    async def test_stream_run_waits_for_slot_as_pending(self, monkeypatch: pytest.MonkeyPatch):
        """A background stream run behind a full limiter stays PENDING, produces
        no events, and starts once the slot frees."""
        from agno.os.managers import event_buffer
        from agno.run.concurrency import background_run_slot

        agent = Agent(name="test-agent")
        stream_started = asyncio.Event()
        release_stream = asyncio.Event()
        release_stream.set()  # do not block execution once started
        self._patch_stream_deps(monkeypatch, stream_started, release_stream)

        holder_started = asyncio.Event()
        release_holder = asyncio.Event()

        async def holder():
            async with background_run_slot():
                holder_started.set()
                await release_holder.wait()

        holder_task = asyncio.create_task(holder())
        await holder_started.wait()

        run_response = RunOutput(run_id="bg-stream-1", session_id="test-session", status=RunStatus.pending)
        run_context = RunContext(run_id="bg-stream-1", session_id="test-session")

        chunks: list = []

        async def consume():
            async for chunk in _run._arun_background_stream(
                agent, run_response=run_response, run_context=run_context, session_id="test-session"
            ):
                chunks.append(chunk)

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0.1)

        # Queued: PENDING everywhere, stream not started, no events emitted
        assert stream_started.is_set() is False
        assert run_response.status == RunStatus.pending
        assert event_buffer.get_run_status("bg-stream-1") == RunStatus.pending
        assert chunks == []

        # Free the slot: the stream should start and complete
        release_holder.set()
        await asyncio.wait_for(stream_started.wait(), timeout=2)
        await asyncio.wait_for(consumer, timeout=2)
        await asyncio.wait_for(holder_task, timeout=2)

        assert len(chunks) == 1
        assert event_buffer.get_run_status("bg-stream-1") == RunStatus.completed
        event_buffer.cleanup_run("bg-stream-1")

    @pytest.mark.asyncio
    async def test_stream_run_cancelled_while_queued(self, monkeypatch: pytest.MonkeyPatch):
        """Cancelling a queued background stream run ends the stream without
        executing and persists CANCELLED."""
        from agno.os.managers import event_buffer
        from agno.run.cancel import cancel_run
        from agno.run.concurrency import background_run_slot

        agent = Agent(name="test-agent")
        stream_started = asyncio.Event()
        release_stream = asyncio.Event()
        self._patch_stream_deps(monkeypatch, stream_started, release_stream)

        holder_started = asyncio.Event()
        release_holder = asyncio.Event()

        async def holder():
            async with background_run_slot():
                holder_started.set()
                await release_holder.wait()

        holder_task = asyncio.create_task(holder())
        await holder_started.wait()

        run_response = RunOutput(run_id="bg-stream-2", session_id="test-session", status=RunStatus.pending)
        run_context = RunContext(run_id="bg-stream-2", session_id="test-session")

        chunks: list = []

        async def consume():
            async for chunk in _run._arun_background_stream(
                agent, run_response=run_response, run_context=run_context, session_id="test-session"
            ):
                chunks.append(chunk)

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0.05)

        cancel_run("bg-stream-2")

        # Stream must terminate without ever executing (poll interval is 0.5s)
        await asyncio.wait_for(consumer, timeout=3)
        assert stream_started.is_set() is False
        assert chunks == []
        assert run_response.status == RunStatus.cancelled
        assert event_buffer.get_run_status("bg-stream-2") == RunStatus.cancelled

        release_holder.set()
        await asyncio.wait_for(holder_task, timeout=2)
        event_buffer.cleanup_run("bg-stream-2")


class TestConcurrentSessionPersistence:
    @pytest.mark.asyncio
    async def test_concurrent_runs_on_one_session_both_reach_terminal_status(self, monkeypatch: pytest.MonkeyPatch):
        """Regression: background tasks used to save the submit-time session
        snapshot, so concurrent runs on ONE session clobbered each other's
        status updates (last writer wins) and polled runs appeared stuck at
        PENDING forever. Status transitions must re-read the session."""
        import copy

        from agno.run.concurrency import set_background_max_concurrency

        set_background_max_concurrency(0)  # both runs execute concurrently
        try:
            agent = Agent(name="test-agent")

            # Simulated DB with whole-blob semantics: reads return deep copies
            # (like deserialization), saves replace the stored runs wholesale.
            store: dict = {"runs": []}

            async def fake_aread_or_create_session(agent, session_id=None, user_id=None):
                return AgentSession(
                    session_id=session_id or "shared", user_id=user_id, runs=copy.deepcopy(store["runs"])
                )

            async def fake_asave_session(agent, session=None):
                store["runs"] = copy.deepcopy(session.runs or [])

            release_a = asyncio.Event()

            async def fake_arun(agent, run_response, run_context, **kwargs):
                # Mimic the real _arun: slow for A, instant for B, then a
                # fresh read-modify-write terminal save.
                if run_response.run_id == "run-a":
                    await release_a.wait()
                run_response.status = RunStatus.completed
                session = await fake_aread_or_create_session(agent, session_id="shared")
                session.upsert_run(run=run_response)
                await fake_asave_session(agent, session=session)
                return run_response

            monkeypatch.setattr(_storage, "aread_or_create_session", fake_aread_or_create_session)
            monkeypatch.setattr(_storage, "update_metadata", lambda agent, session=None: None)
            monkeypatch.setattr("agno.agent._session.asave_session", fake_asave_session)
            monkeypatch.setattr(_run, "_arun", fake_arun)

            for run_id in ("run-a", "run-b"):
                await _run._arun_background(
                    agent,
                    run_response=RunOutput(run_id=run_id, session_id="shared"),
                    run_context=RunContext(run_id=run_id, session_id="shared"),
                    session_id="shared",
                )

            # Let B complete fully while A is still mid-execution, then let A
            # finish - A's later saves must not resurrect B's stale PENDING.
            await asyncio.sleep(0.1)
            release_a.set()
            await asyncio.sleep(0.1)

            statuses = {run.run_id: run.status for run in store["runs"]}
            assert statuses == {"run-a": RunStatus.completed, "run-b": RunStatus.completed}
        finally:
            set_background_max_concurrency(None)
