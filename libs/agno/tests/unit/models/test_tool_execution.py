"""Unit tests for ToolExecution class."""

import pytest

from agno.models.response import ToolExecution


class TestToolExecutionIsPaused:
    """Tests for ToolExecution.is_paused property."""

    def test_is_paused_false_by_default(self):
        """Test that is_paused is False when no pause conditions are set."""
        tool_exec = ToolExecution()
        assert tool_exec.is_paused is False

    def test_is_paused_true_when_requires_confirmation(self):
        """Test that is_paused is True when requires_confirmation is True."""
        tool_exec = ToolExecution(requires_confirmation=True)
        assert tool_exec.is_paused is True

    def test_is_paused_true_when_requires_user_input(self):
        """Test that is_paused is True when requires_user_input is True."""
        tool_exec = ToolExecution(requires_user_input=True)
        assert tool_exec.is_paused is True

    def test_is_paused_true_when_external_execution_required(self):
        """Test that is_paused is True when external_execution_required is True."""
        tool_exec = ToolExecution(external_execution_required=True)
        assert tool_exec.is_paused is True

    def test_is_paused_true_when_stop_after_tool_call(self):
        """Test that is_paused is True when stop_after_tool_call is True.

        This is the fix for GitHub issue #6298: stop_after_tool_call=True
        with output_schema should not cause JSON parsing errors.
        """
        tool_exec = ToolExecution(stop_after_tool_call=True)
        assert tool_exec.is_paused is True

    def test_is_paused_true_with_multiple_conditions(self):
        """Test that is_paused is True when multiple pause conditions are set."""
        tool_exec = ToolExecution(
            requires_confirmation=True,
            stop_after_tool_call=True,
        )
        assert tool_exec.is_paused is True

    def test_is_paused_false_when_confirmed(self):
        """Test that is_paused reflects requires_confirmation regardless of confirmed status."""
        # Note: is_paused checks requires_confirmation, not the confirmed state
        tool_exec = ToolExecution(requires_confirmation=True, confirmed=True)
        assert tool_exec.is_paused is True  # Still paused because requires_confirmation is True
