"""Tests for MCP tool parameter name collision fix (issue #6760).

When an MCP tool has parameters named 'agent', 'team', 'run_context', etc.,
the framework-injected objects must not be overwritten by tool arguments from
the model, and the tool arguments must still reach the MCP server.
"""

from functools import partial
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest

from agno.tools.function import Function, FunctionCall


# ---------------------------------------------------------------------------
# Helpers that simulate MCP's call_tool entrypoint
# ---------------------------------------------------------------------------

class _CallRecorder:
    """Records what arguments call_tool received."""

    def __init__(self):
        self.calls = []


def _make_mcp_entrypoint(recorder: _CallRecorder, tool_name: str):
    """Create a partial entrypoint mimicking get_entrypoint_for_tool().

    Uses a nested async function (not a bound method) to match the real
    MCP entrypoint pattern, which is important for iscoroutinefunction()
    detection on functools.partial objects.
    """

    async def call_tool(
        tool_name: str,
        run_context=None,
        agent=None,
        team=None,
        _tool_arguments: Optional[Dict[str, Any]] = None,
        **kwargs,
    ):
        tool_args = _tool_arguments if _tool_arguments is not None else kwargs
        recorder.calls.append(
            {
                "tool_name": tool_name,
                "agent": agent,
                "team": team,
                "run_context": run_context,
                "tool_args": tool_args,
            }
        )
        return "ok"

    return partial(call_tool, tool_name=tool_name)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMCPParameterCollision:
    """Verify that MCP tool parameters with framework-reserved names
    (agent, team, etc.) do not collide with framework-injected objects."""

    @pytest.mark.asyncio
    async def test_tool_param_named_team_does_not_overwrite_framework_team(self):
        """When an MCP tool has a 'team' parameter, the framework Team object
        must remain intact and the tool's 'team' string must reach the MCP server."""
        recorder = _CallRecorder()
        entrypoint = _make_mcp_entrypoint(recorder, "create_issue")

        mock_team = MagicMock()
        mock_team.name = "FrameworkTeam"

        func = Function(name="create_issue", entrypoint=entrypoint)
        func._team = mock_team
        func._agent = None
        func._run_context = None
        func._images = None
        func._videos = None
        func._audios = None
        func._files = None

        fc = FunctionCall(
            function=func,
            arguments={"team": "engineering", "title": "Bug report"},
        )
        result = await fc.aexecute()

        assert result.status == "success"
        assert len(recorder.calls) == 1

        call = recorder.calls[0]
        # Framework Team object must be preserved
        assert call["team"] is mock_team
        # Tool arguments must include the 'team' string for the MCP server
        assert call["tool_args"]["team"] == "engineering"
        assert call["tool_args"]["title"] == "Bug report"

    @pytest.mark.asyncio
    async def test_tool_param_named_agent_does_not_overwrite_framework_agent(self):
        """When an MCP tool has an 'agent' parameter, the framework Agent object
        must remain intact and the tool's 'agent' string must reach the MCP server."""
        recorder = _CallRecorder()
        entrypoint = _make_mcp_entrypoint(recorder, "assign_task")

        mock_agent = MagicMock()
        mock_agent.name = "FrameworkAgent"

        func = Function(name="assign_task", entrypoint=entrypoint)
        func._team = None
        func._agent = mock_agent
        func._run_context = None
        func._images = None
        func._videos = None
        func._audios = None
        func._files = None

        fc = FunctionCall(
            function=func,
            arguments={"agent": "agent-007", "task": "infiltrate"},
        )
        result = await fc.aexecute()

        assert result.status == "success"
        call = recorder.calls[0]
        assert call["agent"] is mock_agent
        assert call["tool_args"]["agent"] == "agent-007"
        assert call["tool_args"]["task"] == "infiltrate"

    @pytest.mark.asyncio
    async def test_multiple_colliding_params(self):
        """When an MCP tool has BOTH 'agent' and 'team' parameters,
        framework objects must be preserved and both tool values forwarded."""
        recorder = _CallRecorder()
        entrypoint = _make_mcp_entrypoint(recorder, "deploy")

        mock_agent = MagicMock()
        mock_team = MagicMock()

        func = Function(name="deploy", entrypoint=entrypoint)
        func._team = mock_team
        func._agent = mock_agent
        func._run_context = None
        func._images = None
        func._videos = None
        func._audios = None
        func._files = None

        fc = FunctionCall(
            function=func,
            arguments={"agent": "deploy-bot", "team": "platform", "env": "prod"},
        )
        result = await fc.aexecute()

        assert result.status == "success"
        call = recorder.calls[0]
        assert call["agent"] is mock_agent
        assert call["team"] is mock_team
        assert call["tool_args"] == {
            "agent": "deploy-bot",
            "team": "platform",
            "env": "prod",
        }

    @pytest.mark.asyncio
    async def test_no_collision_when_tool_params_are_unique(self):
        """When MCP tool params don't collide with framework names,
        everything works as before."""
        recorder = _CallRecorder()
        entrypoint = _make_mcp_entrypoint(recorder, "search")

        func = Function(name="search", entrypoint=entrypoint)
        func._team = None
        func._agent = None
        func._run_context = None
        func._images = None
        func._videos = None
        func._audios = None
        func._files = None

        fc = FunctionCall(
            function=func,
            arguments={"query": "hello world", "limit": 10},
        )
        result = await fc.aexecute()

        assert result.status == "success"
        call = recorder.calls[0]
        assert call["tool_args"] == {"query": "hello world", "limit": 10}

    @pytest.mark.asyncio
    async def test_no_tool_arguments_passes_empty(self):
        """When tool call has no arguments, _tool_arguments receives None."""
        recorder = _CallRecorder()
        entrypoint = _make_mcp_entrypoint(recorder, "ping")

        func = Function(name="ping", entrypoint=entrypoint)
        func._team = None
        func._agent = None
        func._run_context = None
        func._images = None
        func._videos = None
        func._audios = None
        func._files = None

        fc = FunctionCall(function=func, arguments=None)
        result = await fc.aexecute()

        assert result.status == "success"
        call = recorder.calls[0]
        # No tool arguments → _tool_arguments is None, fallback to empty kwargs
        assert call["tool_args"] == {}

    def test_regular_tool_unaffected(self):
        """Regular (non-MCP) tools that don't have _tool_arguments param
        continue to work with the merge-based approach."""

        call_log = []

        def my_regular_tool(x: int, y: int) -> str:
            call_log.append({"x": x, "y": y})
            return f"{x + y}"

        func = Function(name="add", entrypoint=my_regular_tool)
        func._team = None
        func._agent = None
        func._run_context = None
        func._images = None
        func._videos = None
        func._audios = None
        func._files = None

        fc = FunctionCall(function=func, arguments={"x": 3, "y": 5})
        result = fc.execute()

        assert result.status == "success"
        assert result.result == "8"
        assert call_log == [{"x": 3, "y": 5}]

    @pytest.mark.asyncio
    async def test_sync_execution_with_collision(self):
        """Sync execute() path also handles collisions correctly."""
        # Use a sync function that accepts _tool_arguments
        call_log = []

        def sync_mcp_like(
            tool_name: str,
            agent=None,
            team=None,
            _tool_arguments=None,
            **kwargs,
        ):
            tool_args = _tool_arguments if _tool_arguments is not None else kwargs
            call_log.append({"agent": agent, "team": team, "tool_args": tool_args})
            return "done"

        entrypoint = partial(sync_mcp_like, tool_name="test_tool")
        mock_team = MagicMock()

        func = Function(name="test_tool", entrypoint=entrypoint)
        func._team = mock_team
        func._agent = None
        func._run_context = None
        func._images = None
        func._videos = None
        func._audios = None
        func._files = None

        fc = FunctionCall(
            function=func,
            arguments={"team": "my-team", "data": "value"},
        )
        result = fc.execute()

        assert result.status == "success"
        assert call_log[0]["team"] is mock_team
        assert call_log[0]["tool_args"]["team"] == "my-team"
        assert call_log[0]["tool_args"]["data"] == "value"

    def test_non_mcp_tool_raises_on_collision(self):
        """Non-MCP tools raise TypeError when tool arguments collide with
        framework-injected args, preserving the pre-merge behavior."""

        def my_tool(team=None, task: str = ""):
            return "ok"  # pragma: no cover

        mock_team = MagicMock()

        func = Function(name="my_tool", entrypoint=my_tool)
        func._team = mock_team
        func._agent = None
        func._run_context = None
        func._images = None
        func._videos = None
        func._audios = None
        func._files = None

        fc = FunctionCall(
            function=func,
            arguments={"team": "engineering", "task": "deploy"},
        )
        result = fc.execute()
        assert result.status == "failure"
        assert "got multiple values for argument(s): team" in (result.error or "")
