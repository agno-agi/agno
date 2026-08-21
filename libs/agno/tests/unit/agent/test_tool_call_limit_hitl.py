"""Tests for tool_call_limit enforcement across HITL pause/resume.

Verifies the fix for issue #7962: tool_call_limit should be a per-run budget,
not reset on each model invocation.
"""

from __future__ import annotations

from agno.models.response import ToolExecution
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput


class TestRunOutputExecutedToolCount:
    """Unit tests for RunOutput.executed_tool_count property."""

    def test_counts_all_executed_tools(self):
        run = RunOutput(
            run_id="test",
            session_id="test",
            tools=[
                ToolExecution(tool_call_id="1", tool_name="a", result="done"),
                ToolExecution(tool_call_id="2", tool_name="b", result="done"),
                ToolExecution(tool_call_id="3", tool_name="c", result="done"),
            ],
        )
        assert run.executed_tool_count == 3

    def test_counts_hitl_tools_too(self):
        # All executed tools count, including HITL confirmed ones
        run = RunOutput(
            run_id="test",
            session_id="test",
            tools=[
                ToolExecution(tool_call_id="1", tool_name="a", result="done"),
                ToolExecution(tool_call_id="2", tool_name="b", result="done", confirmed=True),
                ToolExecution(tool_call_id="3", tool_name="c", result="done", confirmed=False),
            ],
        )
        # All 3 have results, so all 3 count
        assert run.executed_tool_count == 3

    def test_excludes_pending_tools(self):
        run = RunOutput(
            run_id="test",
            session_id="test",
            tools=[
                ToolExecution(tool_call_id="1", tool_name="a", result="done"),
                ToolExecution(tool_call_id="2", tool_name="b"),  # No result = pending
            ],
        )
        assert run.executed_tool_count == 1

    def test_returns_zero_for_empty_tools(self):
        run = RunOutput(run_id="test", session_id="test", tools=[])
        assert run.executed_tool_count == 0

        run_none = RunOutput(run_id="test", session_id="test", tools=None)
        assert run_none.executed_tool_count == 0


class TestForkGetsFreshBudget:
    """Forked runs get a fresh tool_call_limit budget via tool_count_at_fork snapshot."""

    def test_fork_subtracts_snapshot(self):
        # Fork inherited 2 executed tools, snapshot=2, then executed 1 more
        run = RunOutput(
            run_id="fork",
            session_id="test",
            forked_from_run_id="parent",
            tool_count_at_fork=2,
            tools=[
                ToolExecution(tool_call_id="1", tool_name="a", result="done"),
                ToolExecution(tool_call_id="2", tool_name="b", result="done"),
                ToolExecution(tool_call_id="3", tool_name="c", result="done"),
            ],
        )
        # 3 total - 2 snapshot = 1 post-fork
        assert run.executed_tool_count == 1

    def test_fork_with_no_post_fork_tools(self):
        run = RunOutput(
            run_id="fork",
            session_id="test",
            forked_from_run_id="parent",
            tool_count_at_fork=2,
            tools=[
                ToolExecution(tool_call_id="1", tool_name="a", result="done"),
                ToolExecution(tool_call_id="2", tool_name="b", result="done"),
            ],
        )
        # 2 total - 2 snapshot = 0 (fresh budget)
        assert run.executed_tool_count == 0

    def test_non_fork_has_zero_snapshot(self):
        # Regular runs have tool_count_at_fork=0 (default)
        run = RunOutput(
            run_id="test",
            session_id="test",
            tools=[
                ToolExecution(tool_call_id="1", tool_name="a", result="done"),
                ToolExecution(tool_call_id="2", tool_name="b", result="done"),
            ],
        )
        assert run.tool_count_at_fork == 0
        assert run.executed_tool_count == 2

    def test_snapshot_clamped_to_zero(self):
        # Edge case: if snapshot > current tools (shouldn't happen but be safe)
        run = RunOutput(
            run_id="fork",
            session_id="test",
            forked_from_run_id="parent",
            tool_count_at_fork=5,
            tools=[
                ToolExecution(tool_call_id="1", tool_name="a", result="done"),
            ],
        )
        # max(0, 1 - 5) = 0, not -4
        assert run.executed_tool_count == 0


class TestTeamRunOutputExecutedToolCount:
    """TeamRunOutput should have the same behavior as RunOutput."""

    def test_team_counts_executed_tools(self):
        run = TeamRunOutput(
            run_id="test",
            session_id="test",
            tools=[
                ToolExecution(tool_call_id="1", tool_name="a", result="done"),
                ToolExecution(tool_call_id="2", tool_name="b", result="done"),
            ],
        )
        assert run.executed_tool_count == 2

    def test_team_fork_gets_fresh_budget(self):
        run = TeamRunOutput(
            run_id="fork",
            session_id="test",
            forked_from_run_id="parent",
            tool_count_at_fork=2,
            tools=[
                ToolExecution(tool_call_id="1", tool_name="a", result="done"),
                ToolExecution(tool_call_id="2", tool_name="b", result="done"),
                ToolExecution(tool_call_id="3", tool_name="c", result="done"),
            ],
        )
        # 3 total - 2 snapshot = 1
        assert run.executed_tool_count == 1


class TestIssue7962Scenario:
    """Test the exact scenario from issue #7962."""

    def test_hitl_tool_counts_toward_limit(self):
        # Issue #7962: With tool_call_limit=1, after HITL tool executes,
        # agent should NOT be able to make another tool call.
        run = RunOutput(
            run_id="test",
            session_id="test",
            tools=[
                ToolExecution(
                    tool_call_id="tc-1",
                    tool_name="send_message",
                    tool_args={"message": "hello"},
                    result='{"status": "success", "message_id": 161}',
                    confirmed=True,
                ),
            ],
        )

        # With the fix: executed_tool_count = 1 (the executed HITL tool)
        # So with tool_call_limit=1, budget is exhausted
        assert run.executed_tool_count == 1, "The HITL tool should count as executed"
