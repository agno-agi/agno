from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.agent.agent import Agent


def test_agent_telemetry():
    """Test that telemetry logging is called during sync agent run."""
    agent = Agent()

    # Assert telemetry is active by default
    assert agent.telemetry

    # Mock the telemetry logging method in the _telemetry module (called by _run.py)
    with patch("agno.agent._telemetry.log_agent_telemetry") as mock_log:
        agent.model = MagicMock()
        agent.run("This is a test run")

        # Assert the telemetry logging func was called
        mock_log.assert_called_once()

        # Assert the telemetry logging func was called with the correct arguments
        call_args = mock_log.call_args
        assert "session_id" in call_args.kwargs
        assert call_args.kwargs["session_id"] is not None
        assert "run_id" in call_args.kwargs
        assert call_args.kwargs["run_id"] is not None


@pytest.mark.asyncio
async def test_agent_telemetry_async():
    """Test that telemetry logging is called during async agent run."""
    agent = Agent()

    # Assert telemetry is active by default
    assert agent.telemetry

    # Mock the async telemetry logging method in the _telemetry module (called by _run.py)
    with patch("agno.agent._telemetry.alog_agent_telemetry") as mock_alog:
        mock_model = AsyncMock()
        mock_model.get_instructions_for_model = MagicMock(return_value=None)
        mock_model.get_system_message_for_model = MagicMock(return_value=None)
        agent.model = mock_model

        await agent.arun("This is a test run")

        # Assert the telemetry logging func was called
        mock_alog.assert_called_once()

        # Assert the telemetry logging func was called with the correct arguments
        call_args = mock_alog.call_args
        assert "session_id" in call_args.kwargs
        assert call_args.kwargs["session_id"] is not None
        assert "run_id" in call_args.kwargs
        assert call_args.kwargs["run_id"] is not None


# =============================================================================
# Non-blocking telemetry tests — verify fire-and-forget behavior
# =============================================================================


def test_create_agent_run_is_non_blocking():
    """create_agent_run should return immediately without waiting for the
    HTTP response to complete. It spawns a daemon thread and returns."""
    import time

    from agno.api.agent import AgentRunCreate, create_agent_run
    from agno.api.api import api

    # Make the actual HTTP call block for a long time inside the daemon thread
    with patch.object(api, "Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post = lambda *a, **kw: time.sleep(3.0)
        mock_client_cls.return_value = mock_client

        run = AgentRunCreate(session_id="s1", run_id="r1")
        start = time.perf_counter()
        create_agent_run(run)
        elapsed = time.perf_counter() - start

        # Should return in under 0.5s — the 3s sleep runs in a daemon thread
        assert elapsed < 0.5, (
            f"create_agent_run blocked for {elapsed:.2f}s, expected immediate return (< 0.5s)"
        )


def test_create_team_run_is_non_blocking():
    """create_team_run should return immediately (fire-and-forget)."""
    import time

    from agno.api.api import api
    from agno.api.team import TeamRunCreate, create_team_run

    with patch.object(api, "Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post = lambda *a, **kw: time.sleep(3.0)
        mock_client_cls.return_value = mock_client

        run = TeamRunCreate(session_id="s1", run_id="r1")
        start = time.perf_counter()
        create_team_run(run)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.5, (
            f"create_team_run blocked for {elapsed:.2f}s, expected immediate return (< 0.5s)"
        )


def test_create_workflow_run_is_non_blocking():
    """create_workflow_run should return immediately (fire-and-forget)."""
    import time

    from agno.api.api import api
    from agno.api.workflow import WorkflowRunCreate, create_workflow_run

    with patch.object(api, "Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post = lambda *a, **kw: time.sleep(3.0)
        mock_client_cls.return_value = mock_client

        run = WorkflowRunCreate(session_id="s1", run_id="r1")
        start = time.perf_counter()
        create_workflow_run(run)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.5, (
            f"create_workflow_run blocked for {elapsed:.2f}s, expected immediate return (< 0.5s)"
        )


@pytest.mark.asyncio
async def test_acreate_agent_run_is_non_blocking():
    """acreate_agent_run should return near-immediately using run_in_executor."""
    import time

    from agno.api.agent import AgentRunCreate, acreate_agent_run
    from agno.api.api import api

    with patch.object(api, "Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post = lambda *a, **kw: time.sleep(3.0)
        mock_client_cls.return_value = mock_client

        run = AgentRunCreate(session_id="s1", run_id="r1")
        start = time.perf_counter()
        await acreate_agent_run(run)
        elapsed = time.perf_counter() - start

        # run_in_executor submits to a thread pool and returns immediately
        assert elapsed < 0.5, (
            f"acreate_agent_run blocked for {elapsed:.2f}s, expected immediate return (< 0.5s)"
        )


@pytest.mark.asyncio
async def test_acreate_team_run_is_non_blocking():
    """acreate_team_run should return near-immediately using run_in_executor."""
    import time

    from agno.api.api import api
    from agno.api.team import TeamRunCreate, acreate_team_run

    with patch.object(api, "Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post = lambda *a, **kw: time.sleep(3.0)
        mock_client_cls.return_value = mock_client

        run = TeamRunCreate(session_id="s1", run_id="r1")
        start = time.perf_counter()
        await acreate_team_run(run)
        elapsed = time.perf_counter() - start

        assert elapsed < 0.5, (
            f"acreate_team_run blocked for {elapsed:.2f}s, expected immediate return (< 0.5s)"
        )
