from unittest.mock import patch

import pytest

from agno.workflow.workflow import Workflow


def test_workflow_telemetry():
    """Test that telemetry logging is called during sync workflow run."""
    workflow = Workflow()

    # Assert telemetry is active by default
    assert workflow.telemetry

    # Mock the telemetry logging method
    with patch.object(workflow, "_log_workflow_telemetry") as mock_log:
        workflow.run("This is a test run")

        # Assert the telemetry logging func was called
        mock_log.assert_called_once()

        # Assert the telemetry logging func was called with the correct arguments
        call_args = mock_log.call_args
        assert "session_id" in call_args.kwargs
        assert call_args.kwargs["session_id"] is not None
        assert "run_id" in call_args.kwargs
        assert call_args.kwargs["run_id"] is not None


@pytest.mark.asyncio
async def test_workflow_telemetry_async():
    """Test that telemetry logging is called during async workflow run."""
    workflow = Workflow()

    # Assert telemetry is active by default
    assert workflow.telemetry

    # Mock the async telemetry logging method
    with patch.object(workflow, "_alog_workflow_telemetry") as mock_alog:
        await workflow.arun("This is a test run")

        # Assert the telemetry logging func was called
        mock_alog.assert_called_once()

        # Assert the telemetry logging func was called with the correct arguments
        call_args = mock_alog.call_args
        assert "session_id" in call_args.kwargs
        assert call_args.kwargs["session_id"] is not None
        assert "run_id" in call_args.kwargs
        assert call_args.kwargs["run_id"] is not None
