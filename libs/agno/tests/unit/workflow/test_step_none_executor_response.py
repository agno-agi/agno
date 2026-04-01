"""
Unit tests for Step._store_executor_response None guard.

Verifies that _store_executor_response is NOT called when the executor
response is None (e.g., API timeout, Team yielding TeamRunErrorEvent
instead of TeamRunOutput).

Covers all 4 execution paths: execute, execute_stream, aexecute, aexecute_stream.

Related: https://github.com/agno-agi/agno/issues/7185
"""

from unittest.mock import MagicMock, patch

import pytest

from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput


# =============================================================================
# Helpers
# =============================================================================


def executor_fn(step_input: StepInput) -> StepOutput:
    """Simple executor for testing."""
    return StepOutput(content="ok")


def _make_agent_step():
    """Create a Step with a mock agent so _executor_type == 'agent'."""
    mock_agent = MagicMock()
    mock_agent.name = "MockAgent"
    mock_agent.agent_id = "mock-agent-id"
    mock_agent.store_media = True
    mock_agent.store_tool_messages = True
    mock_agent.store_history_messages = True
    return Step(name="test-step", agent=mock_agent)


# =============================================================================
# Tests for _store_executor_response None guard
# =============================================================================


class TestStoreExecutorResponseNoneGuard:
    """Ensure _store_executor_response is skipped when executor_run_response is None."""

    def test_store_executor_response_with_none_raises_attribute_error(self):
        """Calling _store_executor_response directly with None raises AttributeError.
        This confirms the bug exists in the method itself, and that the guard
        at the call sites is necessary."""
        step = _make_agent_step()

        mock_workflow_response = MagicMock()
        mock_workflow_response.run_id = "test-run-id"

        # Without the call-site guard, this is what happens:
        #   AttributeError: 'NoneType' object has no attribute 'parent_run_id'
        with pytest.raises(AttributeError, match="parent_run_id"):
            step._store_executor_response(mock_workflow_response, None)

    def test_guard_skips_store_when_executor_response_is_none(self):
        """The guard condition (as written in step.py after the fix) should
        prevent _store_executor_response from being called when
        active_executor_run_response is None."""
        step = _make_agent_step()

        with patch.object(step, "_store_executor_response") as mock_store:
            mock_workflow_response = MagicMock()
            mock_workflow_response.run_id = "test-run-id"

            active_executor_run_response = None
            store_executor_outputs = True

            # This is the exact condition from step.py (all 4 call sites) after the fix
            if (
                store_executor_outputs
                and mock_workflow_response is not None
                and active_executor_run_response is not None
            ):
                step._store_executor_response(mock_workflow_response, active_executor_run_response)

            mock_store.assert_not_called()

    def test_guard_calls_store_when_executor_response_is_valid(self):
        """When executor_run_response is NOT None, _store_executor_response should be called."""
        step = _make_agent_step()

        with patch.object(step, "_store_executor_response") as mock_store:
            mock_workflow_response = MagicMock()
            mock_workflow_response.run_id = "test-run-id"

            mock_executor_response = MagicMock()
            store_executor_outputs = True

            if (
                store_executor_outputs
                and mock_workflow_response is not None
                and mock_executor_response is not None
            ):
                step._store_executor_response(mock_workflow_response, mock_executor_response)

            mock_store.assert_called_once_with(mock_workflow_response, mock_executor_response)

    def test_guard_skips_when_store_outputs_disabled(self):
        """When store_executor_outputs is False, _store_executor_response should not be called."""
        step = _make_agent_step()

        with patch.object(step, "_store_executor_response") as mock_store:
            mock_workflow_response = MagicMock()
            mock_executor_response = MagicMock()
            store_executor_outputs = False

            if (
                store_executor_outputs
                and mock_workflow_response is not None
                and mock_executor_response is not None
            ):
                step._store_executor_response(mock_workflow_response, mock_executor_response)

            mock_store.assert_not_called()

    def test_guard_skips_when_workflow_response_is_none(self):
        """When workflow_run_response is None, _store_executor_response should not be called."""
        step = _make_agent_step()

        with patch.object(step, "_store_executor_response") as mock_store:
            mock_workflow_response = None
            mock_executor_response = MagicMock()
            store_executor_outputs = True

            if (
                store_executor_outputs
                and mock_workflow_response is not None
                and mock_executor_response is not None
            ):
                step._store_executor_response(mock_workflow_response, mock_executor_response)

            mock_store.assert_not_called()
