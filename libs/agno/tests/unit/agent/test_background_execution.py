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
    def test_background_with_stream_raises_value_error(self, monkeypatch: pytest.MonkeyPatch):
        """Background execution cannot be combined with streaming."""
        agent = Agent(name="test-agent")
        _patch_sync_dispatch_dependencies(agent, monkeypatch, runs=[])

        with pytest.raises(ValueError, match="Background execution cannot be combined with streaming"):
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

        async def fake_arun(agent, run_response, run_context, **kwargs):
            run_response.status = RunStatus.completed
            return run_response

        monkeypatch.setattr(_storage, "aread_or_create_session", fake_aread_or_create_session)
        monkeypatch.setattr(_storage, "update_metadata", lambda agent, session=None: None)
        monkeypatch.setattr("agno.agent._session.asave_session", fake_asave_session)
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

        # Background task should have saved RUNNING and then the final state
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

        async def fake_arun_that_fails(agent, run_response, run_context, **kwargs):
            raise RuntimeError("model call failed")

        monkeypatch.setattr(_storage, "aread_or_create_session", fake_aread_or_create_session)
        monkeypatch.setattr(_storage, "update_metadata", lambda agent, session=None: None)
        monkeypatch.setattr("agno.agent._session.asave_session", fake_asave_session)
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

        # Should have persisted ERROR status
        assert RunStatus.error in final_statuses
