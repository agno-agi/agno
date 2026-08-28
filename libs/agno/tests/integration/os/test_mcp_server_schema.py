"""Integration tests for MCP server schema fixes.

Tests that:
1. Custom tools with RunContext/Agent/Team params register without Pydantic crashes
2. structuredContent includes the content field (Claude Code workaround)
"""

import pytest

pytest.importorskip("fastmcp")

from typing import Optional

from fastmcp import Client

from agno.agent.agent import Agent
from agno.os import AgentOS, MCPServerConfig
from agno.os.mcp import build_mcp_server
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.team.team import Team


def _mock_agent() -> Agent:
    """Create a mock agent for schema tests (no model calls needed)."""
    return Agent(name="test-agent", id="test-agent")


# =============================================================================
# Test 1: RunContext param doesn't crash Pydantic schema generation
# =============================================================================


@pytest.mark.asyncio
async def test_run_context_tool_registers_without_pydantic_crash():
    """A custom tool with RunContext param should register without crashing.

    Before the fix, FastMCP would try to generate a JSON schema for RunContext,
    but RunContext contains FilterExpr which Pydantic can't serialize, causing:

        PydanticSchemaGenerationError: Unable to generate pydantic-core schema
    """
    from agno.run import RunContext

    # Note: "user_id" is also excluded by name in MCP, so we use "target_id"
    async def user_lookup(target_id: str, ctx: RunContext) -> str:
        """Look up user by ID using the run context."""
        return f"Found user {target_id} for caller {ctx.user_id}"

    # This would crash before the fix
    os = AgentOS(
        agents=[_mock_agent()],
        mcp_server=MCPServerConfig(tools=[user_lookup], enable_builtin_tools=False),
    )

    async with Client(build_mcp_server(os)) as client:
        tools = await client.list_tools()
        tool_names = [t.name for t in tools]

        # Tool registered successfully
        assert "user_lookup" in tool_names

        # RunContext param is hidden from schema
        user_lookup_tool = next(t for t in tools if t.name == "user_lookup")
        props = user_lookup_tool.inputSchema.get("properties", {})
        assert "ctx" not in props
        assert "target_id" in props


@pytest.mark.asyncio
async def test_agent_typed_param_hidden_from_schema():
    """Agent-typed params are hidden to prevent identity spoofing."""

    async def get_agent_name(helper: Agent) -> str:
        return helper.name

    os = AgentOS(
        agents=[_mock_agent()],
        mcp_server=MCPServerConfig(tools=[get_agent_name], enable_builtin_tools=False),
    )

    async with Client(build_mcp_server(os)) as client:
        tools = await client.list_tools()
        tool = next(t for t in tools if t.name == "get_agent_name")
        props = tool.inputSchema.get("properties", {})

        # Agent param hidden - model can't choose which agent the tool receives
        assert "helper" not in props


@pytest.mark.asyncio
async def test_team_typed_param_hidden_from_schema():
    """Team-typed params are hidden to prevent identity spoofing."""

    async def get_team_info(query: str, team: Optional[Team] = None) -> str:
        return query

    os = AgentOS(
        agents=[_mock_agent()],
        mcp_server=MCPServerConfig(tools=[get_team_info], enable_builtin_tools=False),
    )

    async with Client(build_mcp_server(os)) as client:
        tools = await client.list_tools()
        tool = next(t for t in tools if t.name == "get_team_info")
        props = tool.inputSchema.get("properties", {})

        assert "team" not in props
        assert "query" in props


# =============================================================================
# Test 2: structuredContent includes content field
# =============================================================================


def _stub_arun(component, run_output):
    """Replace component.arun with an async generator yielding the run output."""

    async def fake_arun(message, **kwargs):
        yield run_output

    component.arun = fake_arun  # type: ignore[method-assign]


@pytest.fixture
def _resolve_by_identity(monkeypatch):
    """Resolve run tools to the in-memory (stubbed) component instance."""
    import agno.os.mcp as mcp_mod

    async def _resolve(os, kind, component_id, **kwargs):
        pool = {"agents": os.agents, "teams": os.teams, "workflows": os.workflows}.get(kind) or []
        for component in pool:
            if getattr(component, "id", None) == component_id:
                return component
        return None

    monkeypatch.setattr(mcp_mod, "_resolve_run_component", _resolve)


@pytest.mark.asyncio
async def test_run_agent_structured_content_includes_answer(_resolve_by_identity):
    """run_agent tool result includes content in structuredContent.

    This is a workaround for Claude Code reading structuredContent instead
    of content (known bug). Without this, users see metadata instead of
    the actual agent response.
    """
    agent = _mock_agent()

    # Stub arun to return a fixed response
    mock_output = RunOutput(
        run_id="run-123",
        session_id="sess-456",
        content="Hello from the agent!",
    )
    _stub_arun(agent, mock_output)

    os = AgentOS(agents=[agent], mcp_server=True)

    async with Client(build_mcp_server(os)) as client:
        result = await client.call_tool(
            "run_agent",
            {
                "agent_id": "test-agent",
                "message": "Hello!",
            },
        )

        # Content field exists in text content
        assert result.content[0].text == "Hello from the agent!"

        # Content ALSO in structuredContent (Claude Code workaround)
        assert result.structured_content is not None
        assert result.structured_content.get("content") == "Hello from the agent!"
        assert result.structured_content.get("run_id") == "run-123"
        assert result.structured_content.get("session_id") == "sess-456"


# =============================================================================
# Test 3: String params with framework names are NOT hidden (regression test)
# =============================================================================


@pytest.mark.asyncio
async def test_string_params_named_like_framework_types_not_hidden():
    """Params named 'agent', 'team', 'images' etc. with str type stay visible.

    Regression test for: params were hidden BY NAME regardless of type annotation,
    so `def book(team: str, agent: str)` registered with empty schema and failed.
    Fix: hide params BY TYPE (Agent, Team, RunContext), not by name.
    """

    async def book(team: str, agent: str, images: str, files: str) -> str:
        return f"Booked {agent} on {team} with {images} and {files}"

    os = AgentOS(
        agents=[_mock_agent()],
        mcp_server=MCPServerConfig(tools=[book], enable_builtin_tools=False),
    )

    async with Client(build_mcp_server(os)) as client:
        tools = await client.list_tools()
        tool = next(t for t in tools if t.name == "book")
        props = tool.inputSchema.get("properties", {})

        # All string params visible - not hidden just because of their names
        assert "team" in props, "team:str should not be hidden"
        assert "agent" in props, "agent:str should not be hidden"
        assert "images" in props, "images:str should not be hidden"
        assert "files" in props, "files:str should not be hidden"


# =============================================================================
# Test 4: Multiple framework params all hidden
# =============================================================================


@pytest.mark.asyncio
async def test_multiple_framework_params_all_hidden():
    """A tool with multiple framework params has all of them hidden."""

    async def complex_tool(
        query: str,
        ctx: RunContext,
        agent: Agent,
        team: Optional[Team] = None,
    ) -> str:
        return query

    os = AgentOS(
        agents=[_mock_agent()],
        mcp_server=MCPServerConfig(tools=[complex_tool], enable_builtin_tools=False),
    )

    async with Client(build_mcp_server(os)) as client:
        tools = await client.list_tools()
        tool = next(t for t in tools if t.name == "complex_tool")
        props = tool.inputSchema.get("properties", {})

        # All framework params hidden
        assert "ctx" not in props
        assert "agent" not in props
        assert "team" not in props

        # User param visible
        assert "query" in props
