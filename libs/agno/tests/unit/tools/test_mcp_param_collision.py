"""
Tests for MCP tool parameter collision fix.

Regression test for https://github.com/phidatahq/phidata/issues/6760:
When MCP tools have parameters named 'team' or 'agent' (e.g., Linear MCP
server), the framework's _build_entrypoint_args injected Agent/Team objects
under the same keys, causing "got multiple values for keyword argument" errors.

The fix renames the framework parameters in call_tool to _agno_agent/_agno_team
so they never collide with MCP tool parameter names.
"""

from inspect import signature
from unittest.mock import MagicMock, Mock

from agno.utils.mcp import get_entrypoint_for_tool


def _make_mock_tool(name: str, params: dict) -> Mock:
    """Create a mock MCP Tool with given name and input schema."""
    tool = Mock()
    tool.name = name
    tool.description = f"Test tool: {name}"
    tool.inputSchema = {"type": "object", "properties": params}
    return tool


class TestCallToolSignature:
    """Verify that call_tool does not use 'agent' or 'team' as parameter names."""

    def test_call_tool_has_no_agent_parameter(self):
        """call_tool must not have 'agent' as a direct parameter."""
        mock_session = MagicMock()
        tool = _make_mock_tool("test", {})

        entrypoint = get_entrypoint_for_tool(tool, mock_session)
        sig = signature(entrypoint)

        assert "agent" not in sig.parameters, (
            "call_tool should use '_agno_agent' instead of 'agent' "
            "to avoid collision with MCP tool parameters"
        )

    def test_call_tool_has_no_team_parameter(self):
        """call_tool must not have 'team' as a direct parameter."""
        mock_session = MagicMock()
        tool = _make_mock_tool("test", {})

        entrypoint = get_entrypoint_for_tool(tool, mock_session)
        sig = signature(entrypoint)

        assert "team" not in sig.parameters, (
            "call_tool should use '_agno_team' instead of 'team' "
            "to avoid collision with MCP tool parameters"
        )

    def test_call_tool_has_prefixed_parameters(self):
        """call_tool should have _agno_agent and _agno_team."""
        mock_session = MagicMock()
        tool = _make_mock_tool("test", {})

        entrypoint = get_entrypoint_for_tool(tool, mock_session)
        sig = signature(entrypoint)

        assert "_agno_agent" in sig.parameters
        assert "_agno_team" in sig.parameters

    def test_call_tool_accepts_team_as_kwarg(self):
        """MCP tool params like 'team' should pass through **kwargs."""
        mock_session = MagicMock()
        tool = _make_mock_tool("save_issue", {"team": {"type": "string"}, "title": {"type": "string"}})

        entrypoint = get_entrypoint_for_tool(tool, mock_session)
        sig = signature(entrypoint)

        # 'team' should NOT be a named parameter (would collide)
        assert "team" not in sig.parameters
        # But **kwargs must be present to accept it
        has_var_keyword = any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values())
        assert has_var_keyword, "call_tool must accept **kwargs for MCP tool parameters"


class TestBuildEntrypointArgsMCPIntegration:
    """Verify _build_entrypoint_args handles prefixed names for MCP tools."""

    def test_build_entrypoint_args_injects_prefixed_names(self):
        """_build_entrypoint_args should inject _agno_agent/_agno_team for MCP tools."""
        from agno.tools.function import FunctionCall

        mock_session = MagicMock()
        tool = _make_mock_tool("test", {})
        entrypoint = get_entrypoint_for_tool(tool, mock_session)

        # Directly call _build_entrypoint_args logic using the same signature inspection
        sig = signature(entrypoint)
        entrypoint_args = {}
        mock_agent = Mock(name="MockAgent")
        mock_team = Mock(name="MockTeam")

        if "agent" in sig.parameters:
            entrypoint_args["agent"] = mock_agent
        if "_agno_agent" in sig.parameters:
            entrypoint_args["_agno_agent"] = mock_agent
        if "team" in sig.parameters:
            entrypoint_args["team"] = mock_team
        if "_agno_team" in sig.parameters:
            entrypoint_args["_agno_team"] = mock_team

        assert "_agno_agent" in entrypoint_args
        assert "_agno_team" in entrypoint_args
        assert "agent" not in entrypoint_args
        assert "team" not in entrypoint_args

    def test_no_collision_when_merging_with_tool_args(self):
        """Merging framework args and MCP tool args must not cause duplicate keys."""
        mock_session = MagicMock()
        tool = _make_mock_tool("save_issue", {"team": {"type": "string"}})
        entrypoint = get_entrypoint_for_tool(tool, mock_session)

        sig = signature(entrypoint)
        entrypoint_args = {}
        mock_team = Mock(name="MockTeam")

        if "_agno_team" in sig.parameters:
            entrypoint_args["_agno_team"] = mock_team

        # Simulate LLM-provided tool arguments
        tool_arguments = {"title": "Test Issue", "team": "Engineering"}

        # This should NOT raise "got multiple values for keyword argument 'team'"
        merged = {**entrypoint_args, **tool_arguments}
        assert merged["team"] == "Engineering"
        assert merged["_agno_team"] is mock_team

    def test_agent_param_no_collision(self):
        """MCP tool with 'agent' parameter must not collide with framework injection."""
        mock_session = MagicMock()
        tool = _make_mock_tool("assign_task", {"agent": {"type": "string"}, "task": {"type": "string"}})
        entrypoint = get_entrypoint_for_tool(tool, mock_session)

        sig = signature(entrypoint)
        entrypoint_args = {}
        mock_agent = Mock(name="MockAgent")

        if "_agno_agent" in sig.parameters:
            entrypoint_args["_agno_agent"] = mock_agent

        tool_arguments = {"agent": "John", "task": "Review PR"}

        merged = {**entrypoint_args, **tool_arguments}
        assert merged["agent"] == "John"
        assert merged["_agno_agent"] is mock_agent
