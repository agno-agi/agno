"""
Tests for issue #7175: enable_agentic_state tool schema extraction.

The update_session_state tool should have a proper schema so the LLM knows
how to call it with session_state_updates parameter.
"""

import pytest

from agno.agent import Agent
from agno.agent._tools import aget_tools, get_tools, parse_tools
from agno.run import RunContext
from agno.run.agent import RunOutput


class TestAgenticStateToolSchema:
    """Test that update_session_state tool has correct schema."""

    def test_update_session_state_in_get_tools(self):
        """update_session_state should be present when enable_agentic_state=True."""
        agent = Agent(name="Test", enable_agentic_state=True)

        run_output = RunOutput()
        run_context = RunContext(run_id="test", session_id="test")

        tools = get_tools(agent, run_output, run_context, session=None)

        tool_names = [t.name for t in tools if hasattr(t, "name")]
        assert "update_session_state" in tool_names

    def test_update_session_state_has_entrypoint(self):
        """update_session_state Function should have an entrypoint."""
        agent = Agent(name="Test", enable_agentic_state=True)

        run_output = RunOutput()
        run_context = RunContext(run_id="test", session_id="test")

        tools = get_tools(agent, run_output, run_context, session=None)

        update_tool = next(t for t in tools if hasattr(t, "name") and t.name == "update_session_state")
        assert update_tool.entrypoint is not None

    def test_update_session_state_schema_after_parse_tools(self):
        """After parse_tools(), update_session_state should have proper schema."""
        agent = Agent(name="Test", enable_agentic_state=True)

        run_output = RunOutput()
        run_context = RunContext(run_id="test", session_id="test")

        raw_tools = get_tools(agent, run_output, run_context, session=None)

        # Mock model for parse_tools
        class MockModel:
            supports_native_structured_outputs = False

        parsed_tools = parse_tools(agent, raw_tools, MockModel(), run_context, async_mode=False)

        update_tool = next(t for t in parsed_tools if hasattr(t, "name") and t.name == "update_session_state")

        # Should have session_state_updates in properties
        assert "properties" in update_tool.parameters
        assert "session_state_updates" in update_tool.parameters["properties"], (
            f"Missing session_state_updates in schema. Got: {update_tool.parameters}"
        )

        # Should be required
        assert "session_state_updates" in update_tool.parameters.get("required", []), (
            f"session_state_updates should be required. Got: {update_tool.parameters}"
        )

        # Should NOT have run_context (it's injected)
        assert "run_context" not in update_tool.parameters["properties"], "run_context should be filtered out"

    def test_update_session_state_schema_allows_arbitrary_keys(self):
        """session_state_updates should allow arbitrary keys (additionalProperties: true)."""
        agent = Agent(name="Test", enable_agentic_state=True)

        run_output = RunOutput()
        run_context = RunContext(run_id="test", session_id="test")

        raw_tools = get_tools(agent, run_output, run_context, session=None)

        class MockModel:
            supports_native_structured_outputs = False

        parsed_tools = parse_tools(agent, raw_tools, MockModel(), run_context, async_mode=False)

        update_tool = next(t for t in parsed_tools if hasattr(t, "name") and t.name == "update_session_state")

        param_schema = update_tool.parameters["properties"]["session_state_updates"]

        # The schema should allow arbitrary keys
        # Either additionalProperties is True, or it's not set to False
        additional_props = param_schema.get("additionalProperties")
        assert additional_props is not False, (
            f"session_state_updates should allow arbitrary keys. Got additionalProperties={additional_props}"
        )

    def test_update_session_state_has_description(self):
        """update_session_state should have a description for the LLM."""
        agent = Agent(name="Test", enable_agentic_state=True)

        run_output = RunOutput()
        run_context = RunContext(run_id="test", session_id="test")

        raw_tools = get_tools(agent, run_output, run_context, session=None)

        class MockModel:
            supports_native_structured_outputs = False

        parsed_tools = parse_tools(agent, raw_tools, MockModel(), run_context, async_mode=False)

        update_tool = next(t for t in parsed_tools if hasattr(t, "name") and t.name == "update_session_state")

        assert update_tool.description is not None, "update_session_state should have a description"
        assert len(update_tool.description) > 10, f"Description too short: {update_tool.description}"


class TestAgenticStateToolSchemaAsync:
    """Test async path for update_session_state schema."""

    @pytest.mark.asyncio
    async def test_aget_tools_has_update_session_state(self):
        """aget_tools should include update_session_state with enable_agentic_state=True."""
        agent = Agent(name="Test", enable_agentic_state=True)

        run_output = RunOutput()
        run_context = RunContext(run_id="test", session_id="test")

        tools = await aget_tools(agent, run_output, run_context, session=None, check_mcp_tools=False)

        tool_names = [t.name for t in tools if hasattr(t, "name")]
        assert "update_session_state" in tool_names

    @pytest.mark.asyncio
    async def test_aget_tools_schema_after_parse(self):
        """Async tools should also have proper schema after parsing."""
        agent = Agent(name="Test", enable_agentic_state=True)

        run_output = RunOutput()
        run_context = RunContext(run_id="test", session_id="test")

        raw_tools = await aget_tools(agent, run_output, run_context, session=None, check_mcp_tools=False)

        class MockModel:
            supports_native_structured_outputs = False

        parsed_tools = parse_tools(agent, raw_tools, MockModel(), run_context, async_mode=True)

        update_tool = next(t for t in parsed_tools if hasattr(t, "name") and t.name == "update_session_state")

        assert "session_state_updates" in update_tool.parameters.get("properties", {}), (
            f"Async path missing session_state_updates. Got: {update_tool.parameters}"
        )
