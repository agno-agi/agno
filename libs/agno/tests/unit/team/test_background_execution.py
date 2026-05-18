"""Unit tests for team background execution feature."""

import asyncio
import inspect
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

from agno.run import RunContext
from agno.run.base import RunStatus
from agno.run.cancel import (
    get_cancellation_manager,
    set_cancellation_manager,
)
from agno.run.cancellation_management.in_memory_cancellation_manager import InMemoryRunCancellationManager
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team import _init, _response, _run, _storage
from agno.team.team import Team


@pytest.fixture(autouse=True)
def reset_cancellation_manager():
    original_manager = get_cancellation_manager()
    set_cancellation_manager(InMemoryRunCancellationManager())
    try:
        yield
    finally:
        set_cancellation_manager(original_manager)


def _patch_team_dispatch_dependencies(
    team: Team,
    monkeypatch: pytest.MonkeyPatch,
    runs: Optional[list[Any]] = None,
) -> None:
    monkeypatch.setattr(_init, "_has_async_db", lambda team: False)
    monkeypatch.setattr(_storage, "_update_metadata", lambda team, session=None: None)
    monkeypatch.setattr(_storage, "_load_session_state", lambda team, session=None, session_state=None: session_state)
    monkeypatch.setattr(_run, "_resolve_run_dependencies", lambda team, run_context: None)
    monkeypatch.setattr(_response, "get_response_format", lambda team, run_context=None: None)
    monkeypatch.setattr(
        _storage,
        "_read_or_create_session",
        lambda team, session_id=None, user_id=None: TeamSession(session_id=session_id, user_id=user_id, runs=runs),
    )


# ============= Background execution validation =============


class TestTeamBackgroundValidation:
    def test_background_with_stream_requires_db(self, monkeypatch: pytest.MonkeyPatch):
        """Background execution with streaming requires a database."""
        team = Team(name="test-team", members=[])
        team.db = None
        _patch_team_dispatch_dependencies(team, monkeypatch, runs=[])

        with pytest.raises(ValueError, match="Background execution requires a database"):
            _run.arun_dispatch(team=team, input="hello", stream=True, background=True)

    def test_background_without_db_raises_value_error(self, monkeypatch: pytest.MonkeyPatch):
        """Background execution requires a database."""
        team = Team(name="test-team", members=[])
        team.db = None
        _patch_team_dispatch_dependencies(team, monkeypatch, runs=[])

        with pytest.raises(ValueError, match="Background execution requires a database"):
            _run.arun_dispatch(team=team, input="hello", stream=False, background=True)

    def test_background_dispatch_returns_coroutine(self, monkeypatch: pytest.MonkeyPatch):
        """arun_dispatch with background=True returns a coroutine (not async def itself)."""
        team = Team(name="test-team", members=[])
        team.db = MagicMock()
        _patch_team_dispatch_dependencies(team, monkeypatch, runs=[])

        result = _run.arun_dispatch(team=team, input="hello", stream=False, background=True)
        # arun_dispatch is not async, so it returns a coroutine object
        assert inspect.iscoroutine(result)
        # Clean up the coroutine to avoid warnings
        result.close()


# ============= Background execution lifecycle =============


class TestTeamBackgroundLifecycle:
    @pytest.mark.asyncio
    async def test_arun_background_returns_pending_status(self, monkeypatch: pytest.MonkeyPatch):
        """_arun_background returns immediately with PENDING status."""
        team = Team(name="test-team", members=[])

        async def fake_aread_or_create_session(team, session_id=None, user_id=None):
            return TeamSession(session_id=session_id or "test-session", user_id=user_id, runs=[])

        async def fake_asave_session(team, session=None):
            pass

        async def fake_arun(team, run_response, run_context, **kwargs):
            run_response.status = RunStatus.completed
            run_response.content = "done"
            return run_response

        monkeypatch.setattr(_storage, "_aread_or_create_session", fake_aread_or_create_session)
        monkeypatch.setattr(_storage, "_update_metadata", lambda team, session=None: None)
        monkeypatch.setattr("agno.team._session.asave_session", fake_asave_session)
        monkeypatch.setattr(_run, "_arun", fake_arun)

        run_response = TeamRunOutput(
            run_id="bg-run-1",
            session_id="test-session",
        )
        run_context = RunContext(
            run_id="bg-run-1",
            session_id="test-session",
        )

        result = await _run._arun_background(
            team,
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
        team = Team(name="test-team", members=[])

        persisted_statuses: list[RunStatus] = []

        async def fake_aread_or_create_session(team, session_id=None, user_id=None):
            return TeamSession(session_id=session_id or "test-session", user_id=user_id, runs=[])

        async def fake_asave_session(team, session=None):
            if session and session.runs:
                for run in session.runs:
                    persisted_statuses.append(run.status)

        async def fake_arun(team, run_response, run_context, **kwargs):
            run_response.status = RunStatus.completed
            return run_response

        monkeypatch.setattr(_storage, "_aread_or_create_session", fake_aread_or_create_session)
        monkeypatch.setattr(_storage, "_update_metadata", lambda team, session=None: None)
        monkeypatch.setattr("agno.team._session.asave_session", fake_asave_session)
        monkeypatch.setattr(_run, "_arun", fake_arun)

        run_response = TeamRunOutput(run_id="bg-run-2", session_id="test-session")
        run_context = RunContext(run_id="bg-run-2", session_id="test-session")

        await _run._arun_background(
            team,
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
        team = Team(name="test-team", members=[])

        final_statuses: list[RunStatus] = []

        async def fake_aread_or_create_session(team, session_id=None, user_id=None):
            return TeamSession(session_id=session_id or "test-session", user_id=user_id, runs=[])

        async def fake_asave_session(team, session=None):
            if session and session.runs:
                for run in session.runs:
                    final_statuses.append(run.status)

        async def fake_arun_that_fails(team, run_response, run_context, **kwargs):
            raise RuntimeError("model call failed")

        monkeypatch.setattr(_storage, "_aread_or_create_session", fake_aread_or_create_session)
        monkeypatch.setattr(_storage, "_update_metadata", lambda team, session=None: None)
        monkeypatch.setattr("agno.team._session.asave_session", fake_asave_session)
        monkeypatch.setattr(_run, "_arun", fake_arun_that_fails)

        run_response = TeamRunOutput(run_id="bg-run-err", session_id="test-session")
        run_context = RunContext(run_id="bg-run-err", session_id="test-session")

        result = await _run._arun_background(
            team,
            run_response=run_response,
            run_context=run_context,
            session_id="test-session",
        )

        assert result.status == RunStatus.pending

        # Wait for background task to complete (and fail)
        await asyncio.sleep(0.2)

        # Should have persisted ERROR status
        assert RunStatus.error in final_statuses
