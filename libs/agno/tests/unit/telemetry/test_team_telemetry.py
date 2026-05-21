from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.agent.agent import Agent
from agno.team.team import Team


def test_team_telemetry():
    """Test that telemetry logging is called during sync team run."""
    agent = Agent()
    team = Team(members=[agent])

    # Assert telemetry is active by default
    assert team.telemetry

    # Mock the telemetry logging method in the _telemetry module (called by _run.py)
    with patch("agno.team._telemetry.log_team_telemetry") as mock_log:
        agent.model = MagicMock()
        team.model = MagicMock()
        team.run("This is a test run")

        # Assert the telemetry logging func was called
        mock_log.assert_called_once()

        # Assert the telemetry logging func was called with the correct arguments
        call_args = mock_log.call_args
        assert "session_id" in call_args.kwargs
        assert call_args.kwargs["session_id"] is not None
        assert "run_id" in call_args.kwargs
        assert call_args.kwargs["run_id"] is not None


@pytest.mark.asyncio
async def test_team_telemetry_async():
    """Test that telemetry logging is called during async team run."""
    agent = Agent()
    team = Team(members=[agent])

    # Assert telemetry is active by default
    assert team.telemetry

    # Mock the async telemetry logging method in the _telemetry module (called by _run.py)
    with patch("agno.team._telemetry.alog_team_telemetry") as mock_alog:
        mock_model = AsyncMock()
        mock_model.get_instructions_for_model = MagicMock(return_value=None)
        mock_model.get_system_message_for_model = MagicMock(return_value=None)
        agent.model = mock_model
        team.model = mock_model
        await team.arun("This is a test run")

        # Assert the telemetry logging func was called
        mock_alog.assert_called_once()

        # Assert the telemetry logging func was called with the correct arguments
        call_args = mock_alog.call_args
        assert "session_id" in call_args.kwargs
        assert call_args.kwargs["session_id"] is not None
        assert "run_id" in call_args.kwargs
        assert call_args.kwargs["run_id"] is not None
