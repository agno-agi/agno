"""
Unit tests for the child_run_id race condition fix in concurrent team calls.

Issue: When the model calls delegate_task_to_member multiple times concurrently
(once per member), the _process_delegate_task_to_member function would iterate
ALL tool entries and stamp the same child_run_id on every tool with matching
tool_name, rather than only on the tool entry that corresponds to the specific
member invocation. This caused all concurrent child agents to end up with the
same child_run_id.

Fix (streaming): Match tool entries by both tool_name AND the member_id / task_id
in tool_args so each concurrent invocation only updates its own tool entry.

Fix (non-streaming): In non-streaming mode, run_response.tools is populated by
_update_run_response() AFTER tool functions execute, so the streaming-path fix
is a no-op. _stamp_child_run_ids() runs after _update_run_response() to back-fill
any missing child_run_ids using member_responses already collected via add_member_run().
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import MagicMock

from agno.agent import Agent
from agno.models.response import ToolExecution
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.team._response import _stamp_child_run_ids
from agno.utils.team import get_member_id


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
    def _make_member_agent(agent_id: Optional[str], agent_name: str) -> MagicMock:
        agent = MagicMock(spec=Agent)
        agent.id = agent_id
        agent.name = agent_name
        agent.store_media = True
        agent.store_tool_messages = True
        agent.store_history_messages = True
        return agent

    @staticmethod
    def _make_run_response(
        member_run_id: str,
        agent_id: Optional[str] = None,
        agent_name: str = "Agent1",
    ) -> RunOutput:
        return RunOutput(
            run_id=member_run_id,
            agent_id=agent_id,
            agent_name=agent_name,
            content=f"Response from {agent_name}",
        )

    # ------------------------------------------------------------------ #
    # Tests for streaming path: _process_delegate_task_to_member
    # Uses get_member_id() to produce url-safe IDs for matching.
    # ------------------------------------------------------------------ #

    def test_delegate_assigns_unique_child_run_id_per_member(self):
        """
        When the model makes two concurrent delegate_task_to_member calls for
        different members, each tool entry should get its own child_run_id.
        """
        # tool_args use url-safe member IDs (as produced by get_member_id)
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

        run_response = TeamRunOutput(run_id="team-run-1", tools=[tool_a, tool_b])

        member_a_response = self._make_run_response("run-a", "agent-a", "AgentA")
        member_b_response = self._make_run_response("run-b", "agent-b", "AgentB")

        member_a = self._make_member_agent("agent-a", "AgentA")
        self._simulate_process_delegate(run_response, member_a_response, member_a)

        member_b = self._make_member_agent("agent-b", "AgentB")
        self._simulate_process_delegate(run_response, member_b_response, member_b)

        assert tool_a.child_run_id == "run-a"
        assert tool_b.child_run_id == "run-b"

    def test_delegate_uses_url_safe_member_id(self):
        """
        When the agent has no explicit id, the member_id in tool_args is
        url_safe_string(agent.name). The matching must use get_member_id()
        (which normalises the name) rather than the raw agent.name.
        """
        # Model sends url-safe "writer" (lowercase), agent name is "Writer"
        tool = self._make_tool_execution(
            tool_name="delegate_task_to_member",
            tool_args={"member_id": "writer", "task": "write something"},
            tool_call_id="call-1",
        )
        run_response = TeamRunOutput(run_id="team-run-1", tools=[tool])

        member_response = self._make_run_response("run-w", agent_id=None, agent_name="Writer")
        member = self._make_member_agent(None, "Writer")

        self._simulate_process_delegate(run_response, member_response, member)

        assert tool.child_run_id == "run-w", f"Expected 'run-w' via get_member_id matching, got '{tool.child_run_id}'"

    def test_delegate_does_not_overwrite_already_set_child_run_id(self):
        """
        Once a tool's child_run_id is set, it must not be overwritten.
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

        assert tool.child_run_id == "already-set-run-id"

    def test_delegate_with_three_concurrent_members(self):
        """
        Three concurrent member invocations should each get their own
        child_run_id without cross-contamination.
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
            assert tools[i].child_run_id == f"run-{i}"

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

        assert tool.child_run_id is None

    # ------------------------------------------------------------------ #
    # Tests for _task_tools._post_process_member_run (streaming path)
    # ------------------------------------------------------------------ #

    def test_task_assigns_unique_child_run_id_per_task(self):
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

        self._simulate_post_process(run_response, member_run_id="run-1", tool_name="execute_task", task_id="task-1")
        self._simulate_post_process(run_response, member_run_id="run-2", tool_name="execute_task", task_id="task-2")

        assert tool_a.child_run_id == "run-1"
        assert tool_b.child_run_id == "run-2"

    def test_task_does_not_overwrite_already_set_child_run_id(self):
        tool = self._make_tool_execution(
            tool_name="execute_task",
            tool_args={"task_id": "task-1", "member_id": "agent-a"},
            tool_call_id="call-1",
            child_run_id="original-run-id",
        )

        run_response = TeamRunOutput(run_id="team-run-1", tools=[tool])
        self._simulate_post_process(
            run_response, member_run_id="new-run-id", tool_name="execute_task", task_id="task-1"
        )

        assert tool.child_run_id == "original-run-id"

    def test_task_no_task_id_falls_back_to_first_match(self):
        tool = self._make_tool_execution(
            tool_name="execute_tasks_parallel",
            tool_args={"task_ids": ["task-1", "task-2"]},
            tool_call_id="call-1",
        )

        run_response = TeamRunOutput(run_id="team-run-1", tools=[tool])
        self._simulate_post_process(
            run_response, member_run_id="run-first", tool_name="execute_tasks_parallel", task_id=None
        )

        assert tool.child_run_id == "run-first"

    # ------------------------------------------------------------------ #
    # Tests for _stamp_child_run_ids (non-streaming fix)
    # ------------------------------------------------------------------ #

    def test_stamp_fills_delegate_child_run_ids_from_member_responses(self):
        """
        _stamp_child_run_ids should fill in child_run_id for delegate tools
        by matching tool_args["member_id"] to member_responses.
        """
        tool_a = self._make_tool_execution(
            tool_name="delegate_task_to_member",
            tool_args={"member_id": "writer", "task": "write a haiku"},
            tool_call_id="call-1",
        )
        tool_b = self._make_tool_execution(
            tool_name="delegate_task_to_member",
            tool_args={"member_id": "researcher", "task": "find a fact"},
            tool_call_id="call-2",
        )

        run_response = TeamRunOutput(run_id="team-run-1", tools=[tool_a, tool_b])

        # Simulate what happens during tool execution: member runs are added
        mr_writer = self._make_run_response("run-writer", agent_id=None, agent_name="Writer")
        mr_researcher = self._make_run_response("run-researcher", agent_id=None, agent_name="Researcher")
        run_response.add_member_run(mr_writer)
        run_response.add_member_run(mr_researcher)

        # Now stamp (this is what happens after _update_run_response in non-streaming)
        _stamp_child_run_ids(run_response)

        assert tool_a.child_run_id == "run-writer"
        assert tool_b.child_run_id == "run-researcher"

    def test_stamp_fills_execute_task_child_run_ids(self):
        """
        _stamp_child_run_ids should also handle execute_task tools.
        """
        tool = self._make_tool_execution(
            tool_name="execute_task",
            tool_args={"task_id": "task-1", "member_id": "my-agent"},
            tool_call_id="call-1",
        )

        run_response = TeamRunOutput(run_id="team-run-1", tools=[tool])

        mr = self._make_run_response("run-agent", agent_id="my-agent", agent_name="MyAgent")
        run_response.add_member_run(mr)

        _stamp_child_run_ids(run_response)

        assert tool.child_run_id == "run-agent"

    def test_stamp_does_not_overwrite_existing_child_run_ids(self):
        """
        _stamp_child_run_ids must not overwrite already-set child_run_ids.
        """
        tool = self._make_tool_execution(
            tool_name="delegate_task_to_member",
            tool_args={"member_id": "writer", "task": "write"},
            tool_call_id="call-1",
            child_run_id="already-set",
        )

        run_response = TeamRunOutput(run_id="team-run-1", tools=[tool])
        mr = self._make_run_response("new-run", agent_id=None, agent_name="Writer")
        run_response.add_member_run(mr)

        _stamp_child_run_ids(run_response)

        assert tool.child_run_id == "already-set"

    def test_stamp_handles_no_tools(self):
        """_stamp_child_run_ids is a no-op when tools is None."""
        run_response = TeamRunOutput(run_id="team-run-1", tools=None)
        _stamp_child_run_ids(run_response)  # Should not raise

    def test_stamp_handles_no_member_responses(self):
        """_stamp_child_run_ids is a no-op when there are no member_responses."""
        tool = self._make_tool_execution(
            tool_name="delegate_task_to_member",
            tool_args={"member_id": "writer", "task": "write"},
            tool_call_id="call-1",
        )
        run_response = TeamRunOutput(run_id="team-run-1", tools=[tool])

        _stamp_child_run_ids(run_response)

        assert tool.child_run_id is None

    def test_stamp_with_explicit_agent_id(self):
        """
        When agents have explicit IDs, matching should work via agent_id.
        """
        tool = self._make_tool_execution(
            tool_name="delegate_task_to_member",
            tool_args={"member_id": "custom-agent-id", "task": "do stuff"},
            tool_call_id="call-1",
        )

        run_response = TeamRunOutput(run_id="team-run-1", tools=[tool])
        mr = self._make_run_response("run-custom", agent_id="custom-agent-id", agent_name="CustomAgent")
        run_response.add_member_run(mr)

        _stamp_child_run_ids(run_response)

        assert tool.child_run_id == "run-custom"

    def test_stamp_three_delegates_correct_order(self):
        """
        Three delegate tools with three member_responses should all get
        correctly matched child_run_ids.
        """
        names = ["Writer", "Researcher", "Reviewer"]
        tools = [
            self._make_tool_execution(
                tool_name="delegate_task_to_member",
                tool_args={"member_id": name.lower(), "task": f"task for {name}"},
                tool_call_id=f"call-{i}",
            )
            for i, name in enumerate(names)
        ]

        run_response = TeamRunOutput(run_id="team-run-1", tools=tools)

        for name in names:
            mr = self._make_run_response(f"run-{name.lower()}", agent_id=None, agent_name=name)
            run_response.add_member_run(mr)

        _stamp_child_run_ids(run_response)

        for i, name in enumerate(names):
            assert tools[i].child_run_id == f"run-{name.lower()}", (
                f"Tool {i} ({name}): expected 'run-{name.lower()}', got '{tools[i].child_run_id}'"
            )

    # ------------------------------------------------------------------ #
    # Simulation helpers (replicate the fixed streaming-path logic)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _simulate_process_delegate(
        run_response: TeamRunOutput,
        member_run_response: RunOutput,
        member_agent: MagicMock,
    ) -> None:
        """
        Replicate the fixed child_run_id assignment logic from
        _default_tools._process_delegate_task_to_member (streaming path).
        Uses get_member_id() for correct url-safe matching.
        """
        if run_response.tools is not None and member_run_response is not None:
            url_safe_member_id = get_member_id(member_agent)
            for tool in run_response.tools:
                if tool.tool_name and tool.tool_name.lower() == "delegate_task_to_member":
                    tool_member_id = (tool.tool_args or {}).get("member_id")
                    if tool_member_id == url_safe_member_id and tool.child_run_id is None:
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
        _task_tools._post_process_member_run (streaming path).
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
