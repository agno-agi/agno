"""Regression tests: session persistence survives CancelledError during cleanup.

Guards against the silent 404-on-reconnect bug where CancelledError from
middleware cancel scopes (e.g. Starlette BaseHTTPMiddleware on client disconnect)
kills session persistence in _acleanup_and_store.

Tests verify:
  1. _acleanup_and_store completes session save even when caller is cancelled
  2. Exceptions in shielded cleanup are logged, not silently dropped
  3. All CancelledError handlers in run functions call _acleanup_and_store
"""

import ast
import asyncio
import inspect
import textwrap
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.run import RunStatus
from agno.team import _run as team_run
from agno.team._run import _acleanup_and_store
from agno.session.team import TeamSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_team() -> MagicMock:
    """Create a minimal mock Team with async session save."""
    team = MagicMock()
    team.asave_session = AsyncMock()
    team.db = MagicMock()
    team.store_media = True
    team.store_tool_messages = True
    team.store_history_messages = True
    return team


def _make_mock_run_response() -> MagicMock:
    """Create a minimal mock TeamRunOutput."""
    rr = MagicMock()
    rr.metrics = None
    rr.status = RunStatus.completed
    rr.run_id = "test-run-id"
    rr.session_state = None
    return rr


def _make_mock_session() -> MagicMock:
    """Create a minimal mock TeamSession."""
    session = MagicMock(spec=TeamSession)
    session.session_data = None
    return session


def _get_cancel_handler_source(func: object) -> str:
    """Extract source of the CancelledError except block from a function."""
    source = textwrap.dedent(inspect.getsource(func))
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        handler_source = ast.get_source_segment(source, node)
        if handler_source and "CancelledError" in handler_source:
            return handler_source
    raise AssertionError(
        f"{getattr(func, '__name__', func)} has no except handler catching asyncio.CancelledError"
    )


# ---------------------------------------------------------------------------
# Behavioral: _acleanup_and_store completes save under cancellation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_completes_session_save_on_cancel():
    """Session save must complete even when the calling task is cancelled.

    Simulates the real bug: caller awaits _acleanup_and_store, then gets
    cancelled by a middleware cancel scope.  The shielded inner task must
    still call asave_session to completion.
    """
    team = _make_mock_team()
    run_response = _make_mock_run_response()
    session = _make_mock_session()

    save_entered = asyncio.Event()
    save_completed = asyncio.Event()

    async def tracked_save(**kwargs):
        save_entered.set()
        # Yield control so the cancel can fire while we're mid-save.
        await asyncio.sleep(0)
        save_completed.set()

    team.asave_session = AsyncMock(side_effect=tracked_save)

    async def caller():
        await _acleanup_and_store(team, run_response, session)

    task = asyncio.ensure_future(caller())
    await save_entered.wait()
    task.cancel()

    # Let the caller handle cancellation.
    try:
        await task
    except asyncio.CancelledError:
        pass

    # Wait for the shielded background task to signal completion.
    await asyncio.wait_for(save_completed.wait(), timeout=2.0)

    assert save_completed.is_set(), (
        "asave_session did not complete — session save was killed by CancelledError"
    )


@pytest.mark.asyncio
async def test_cleanup_completes_normally_without_cancel():
    """Normal (non-cancelled) path: _acleanup_and_store awaits save inline."""
    team = _make_mock_team()
    run_response = _make_mock_run_response()
    session = _make_mock_session()

    await _acleanup_and_store(team, run_response, session)

    team.asave_session.assert_called_once_with(session=session)


@pytest.mark.asyncio
async def test_cleanup_logs_exception_on_cancelled_path():
    """When caller is cancelled AND the inner task fails, done-callback must log it."""
    team = _make_mock_team()
    run_response = _make_mock_run_response()
    run_response.status = None  # Skip approval update path
    session = _make_mock_session()

    save_entered = asyncio.Event()

    async def failing_save(**kwargs):
        save_entered.set()
        await asyncio.sleep(0)
        raise RuntimeError("DB connection lost")

    team.asave_session = AsyncMock(side_effect=failing_save)

    async def caller():
        await _acleanup_and_store(team, run_response, session)

    with patch.object(team_run, "log_warning") as mock_warn:
        task = asyncio.ensure_future(caller())
        await save_entered.wait()
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

        # Wait for the shielded task to fail and the done-callback to fire.
        await asyncio.sleep(0.1)

        warn_messages = [str(call) for call in mock_warn.call_args_list]
        assert any("DB connection lost" in msg for msg in warn_messages), (
            f"Expected cleanup exception to be logged via done-callback, got: {warn_messages}"
        )


@pytest.mark.asyncio
async def test_cleanup_propagates_exception_on_normal_path():
    """On the non-cancelled path, cleanup exceptions propagate to the caller."""
    team = _make_mock_team()
    team.asave_session = AsyncMock(side_effect=RuntimeError("DB connection lost"))
    run_response = _make_mock_run_response()
    run_response.status = None
    session = _make_mock_session()

    with pytest.raises(RuntimeError, match="DB connection lost"):
        await _acleanup_and_store(team, run_response, session)


# ---------------------------------------------------------------------------
# Structural: all CancelledError handlers call _acleanup_and_store
# ---------------------------------------------------------------------------


def test_arun_tasks_calls_cleanup_on_cancel():
    """_arun_tasks CancelledError handler must call _acleanup_and_store."""
    branch = _get_cancel_handler_source(team_run._arun_tasks)
    assert "_acleanup_and_store" in branch, (
        "_arun_tasks CancelledError branch must call _acleanup_and_store"
    )


def test_arun_tasks_stream_calls_cleanup_on_cancel():
    """_arun_tasks_stream CancelledError handler must call _acleanup_and_store."""
    branch = _get_cancel_handler_source(team_run._arun_tasks_stream)
    assert "_acleanup_and_store" in branch, (
        "_arun_tasks_stream CancelledError branch must call _acleanup_and_store"
    )


def test_arun_calls_cleanup_on_cancel():
    """_arun CancelledError handler must call _acleanup_and_store."""
    branch = _get_cancel_handler_source(team_run._arun)
    assert "_acleanup_and_store" in branch, (
        "_arun CancelledError branch must call _acleanup_and_store"
    )


def test_arun_stream_calls_cleanup_on_cancel():
    """_arun_stream CancelledError handler must call _acleanup_and_store."""
    branch = _get_cancel_handler_source(team_run._arun_stream)
    assert "_acleanup_and_store" in branch, (
        "_arun_stream CancelledError branch must call _acleanup_and_store"
    )
