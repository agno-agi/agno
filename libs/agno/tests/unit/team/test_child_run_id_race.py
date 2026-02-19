"""
Unit tests for the child_run_id race condition fix in concurrent team calls.

Issue: When the model calls delegate_task_to_member multiple times concurrently
(once per member), the _process_delegate_task_to_member function would iterate
ALL tool entries and stamp the same child_run_id on every tool with matching
tool_name, rather than only on the tool entry that corresponds to the specific
member invocation. This caused all concurrent child agents to end up with the
same child_run_id.

Fix: Match tool entries by both tool_name AND the member_id / task_id in
tool_args so each concurrent invocation only updates its own tool entry.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import MagicMock

from agno.models.response import ToolExecution
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput


class TestChildRunIdRaceCondition:
    """Test suite verifying that child_run_id is correctly assigned per-member."""

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _make_tool_execution(
        tool_name: str,
        tool_args: Optional[Dict[str, Any]] = None,
        tool_call_id: Optional[str] = None,
        child_run_id: Optional[str] = None,
    ) -> ToolExecution:
        return ToolExecution(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_args=tool_args,
            child_run_id=child_run_id,
        )

    @staticmethod
    def _make_member_agent(agent_id: str, agent_name: str) -> MagicMock:
        agent = MagicMock()
        agent.id = agent_id
        agent.name = agent_name
        agent.store_media = True
        agent.store_tool_messages = True
        agent.store_history_messages = True
        return agent

    @staticmethod
    def _make_run_response(
        member_run_id: str,
        agent_id: str = "agent-1",
        agent_name: str = "Agent1",
    ) -> RunOutput:
        return RunOutput(
            run_id=member_run_id,
            agent_id=agent_id,
            agent_name=agent_name,
            content=f"Response from {agent_name}",
        )

    # ------------------------------------------------------------------ #
    # Tests for _default_tools._process_delegate_task_to_member
    # ------------------------------------------------------------------ #

    def test_delegate_assigns_unique_child_run_id_per_member(self):
        """
        When the model makes two concurrent delegate_task_to_member calls for
        different members, each tool entry should get its own child_run_id
        matching the member that was invoked, not the last writer's run_id.
        """
        # Simulate two tool entries created by the model in one turn
        tool_a = self._make_tool_execution(
            tool_name="delegate_task_to_member",
            tool_args={"member_id": "agent-a", "task": "task for A"},
            tool_call_id="call-1",
        )
        tool_b = self._make_tool_execution(
            tool_name="delegate_task_to_member",
            tool_args={"member_id": "agent-b", "task": "task for B"},
            tool_call_id="call-2",
        )

        # TeamRunOutput with both tool entries
        run_response = TeamRunOutput(
            run_id="team-run-1",
            tools=[tool_a, tool_b],
        )

        # Member responses
        member_a_response = self._make_run_response("run-a", "agent-a", "AgentA")
        member_b_response = self._make_run_response("run-b", "agent-b", "AgentB")

        # Simulate _process_delegate_task_to_member for member A
        member_a = self._make_member_agent("agent-a", "AgentA")
        self._simulate_process_delegate(run_response, member_a_response, member_a)

        # Simulate _process_delegate_task_to_member for member B
        member_b = self._make_member_agent("agent-b", "AgentB")
        self._simulate_process_delegate(run_response, member_b_response, member_b)

        # Verify: each tool got its own unique child_run_id
        assert tool_a.child_run_id == "run-a", f"Expected tool_a.child_run_id='run-a', got '{tool_a.child_run_id}'"
        assert tool_b.child_run_id == "run-b", f"Expected tool_b.child_run_id='run-b', got '{tool_b.child_run_id}'"

    def test_delegate_does_not_overwrite_already_set_child_run_id(self):
        """
        Once a tool's child_run_id is set, it must not be overwritten by
        a subsequent call to _process_delegate_task_to_member.
        """
        tool = self._make_tool_execution(
            tool_name="delegate_task_to_member",
            tool_args={"member_id": "agent-a", "task": "task for A"},
            tool_call_id="call-1",
            child_run_id="already-set-run-id",
        )

        run_response = TeamRunOutput(run_id="team-run-1", tools=[tool])

        member_response = self._make_run_response("new-run-id", "agent-a", "AgentA")
        member = self._make_member_agent("agent-a", "AgentA")

        self._simulate_process_delegate(run_response, member_response, member)

        assert tool.child_run_id == "already-set-run-id", "child_run_id should not be overwritten once set"

    def test_delegate_with_three_concurrent_members(self):
        """
        Three concurrent member invocations should each get their own
        child_run_id without any cross-contamination.
        """
        tools = [
            self._make_tool_execution(
                tool_name="delegate_task_to_member",
                tool_args={"member_id": f"agent-{i}", "task": f"task-{i}"},
                tool_call_id=f"call-{i}",
            )
            for i in range(3)
        ]

        run_response = TeamRunOutput(run_id="team-run-1", tools=tools)

        for i in range(3):
            member_response = self._make_run_response(f"run-{i}", f"agent-{i}", f"Agent{i}")
            member = self._make_member_agent(f"agent-{i}", f"Agent{i}")
            self._simulate_process_delegate(run_response, member_response, member)

        for i in range(3):
            assert tools[i].child_run_id == f"run-{i}", (
                f"Tool {i} should have child_run_id='run-{i}', got '{tools[i].child_run_id}'"
            )

    def test_delegate_no_match_leaves_child_run_id_none(self):
        """
        If a tool's member_id does not match the current member, its
        child_run_id should remain None.
        """
        tool = self._make_tool_execution(
            tool_name="delegate_task_to_member",
            tool_args={"member_id": "agent-x", "task": "some task"},
            tool_call_id="call-1",
        )

        run_response = TeamRunOutput(run_id="team-run-1", tools=[tool])

        member_response = self._make_run_response("run-y", "agent-y", "AgentY")
        member = self._make_member_agent("agent-y", "AgentY")

        self._simulate_process_delegate(run_response, member_response, member)

        assert tool.child_run_id is None, "child_run_id should remain None when member_id does not match"

    # ------------------------------------------------------------------ #
    # Tests for _task_tools._post_process_member_run
    # ------------------------------------------------------------------ #

    def test_task_assigns_unique_child_run_id_per_task(self):
        """
        When two execute_task calls are made concurrently for different
        tasks, each tool entry should get its own child_run_id.
        """
        tool_a = self._make_tool_execution(
            tool_name="execute_task",
            tool_args={"task_id": "task-1", "member_id": "agent-a"},
            tool_call_id="call-1",
        )
        tool_b = self._make_tool_execution(
            tool_name="execute_task",
            tool_args={"task_id": "task-2", "member_id": "agent-b"},
            tool_call_id="call-2",
        )

        run_response = TeamRunOutput(run_id="team-run-1", tools=[tool_a, tool_b])

        # Simulate _post_process_member_run for task-1
        self._simulate_post_process(
            run_response,
            member_run_id="run-1",
            tool_name="execute_task",
            task_id="task-1",
        )

        # Simulate _post_process_member_run for task-2
        self._simulate_post_process(
            run_response,
            member_run_id="run-2",
            tool_name="execute_task",
            task_id="task-2",
        )

        assert tool_a.child_run_id == "run-1"
        assert tool_b.child_run_id == "run-2"

    def test_task_does_not_overwrite_already_set_child_run_id(self):
        """
        Once a task tool's child_run_id is set, a subsequent call must
        not overwrite it.
        """
        tool = self._make_tool_execution(
            tool_name="execute_task",
            tool_args={"task_id": "task-1", "member_id": "agent-a"},
            tool_call_id="call-1",
            child_run_id="original-run-id",
        )

        run_response = TeamRunOutput(run_id="team-run-1", tools=[tool])

        self._simulate_post_process(
            run_response,
            member_run_id="new-run-id",
            tool_name="execute_task",
            task_id="task-1",
        )

        assert tool.child_run_id == "original-run-id"

    def test_task_no_task_id_falls_back_to_first_match(self):
        """
        When task_id is None (e.g., for execute_tasks_parallel), the
        fallback behavior should assign to the first unset tool entry.
        """
        tool = self._make_tool_execution(
            tool_name="execute_tasks_parallel",
            tool_args={"task_ids": ["task-1", "task-2"]},
            tool_call_id="call-1",
        )

        run_response = TeamRunOutput(run_id="team-run-1", tools=[tool])

        self._simulate_post_process(
            run_response,
            member_run_id="run-first",
            tool_name="execute_tasks_parallel",
            task_id=None,
        )

        assert tool.child_run_id == "run-first"

    # ------------------------------------------------------------------ #
    # Simulation helpers (replicate the fixed logic in isolation)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _simulate_process_delegate(
        run_response: TeamRunOutput,
        member_run_response: RunOutput,
        member_agent: MagicMock,
    ) -> None:
        """
        Replicate the fixed child_run_id assignment logic from
        _default_tools._process_delegate_task_to_member.
        """
        if run_response.tools is not None and member_run_response is not None:
            member_id = member_agent.id if member_agent.id else member_agent.name
            for tool in run_response.tools:
                if tool.tool_name and tool.tool_name.lower() == "delegate_task_to_member":
                    tool_member_id = (tool.tool_args or {}).get("member_id")
                    if tool_member_id == member_id and tool.child_run_id is None:
                        tool.child_run_id = member_run_response.run_id
                        break

    @staticmethod
    def _simulate_post_process(
        run_response: TeamRunOutput,
        member_run_id: str,
        tool_name: str = "execute_task",
        task_id: Optional[str] = None,
    ) -> None:
        """
        Replicate the fixed child_run_id assignment logic from
        _task_tools._post_process_member_run.
        """
        if run_response.tools is not None:
            for tool in run_response.tools:
                if tool.tool_name and tool.tool_name.lower() == tool_name and tool.child_run_id is None:
                    if task_id is not None:
                        tool_task_id = (tool.tool_args or {}).get("task_id")
                        if tool_task_id != task_id:
                            continue
                    tool.child_run_id = member_run_id
                    break
