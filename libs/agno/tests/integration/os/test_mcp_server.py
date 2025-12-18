"""Integration tests for MCP server tools in AgentOS.

These tests verify that the MCP tools are properly registered.
"""

import pytest

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.os import AgentOS

# --- Fixtures ---


@pytest.fixture
def test_db():
    """Create a test in-memory database."""
    return InMemoryDb()


@pytest.fixture
def test_agent(test_db):
    """Create a test agent with a database."""
    return Agent(name="test-agent", id="test-agent-id", db=test_db)


# --- Expected Tools ---

EXPECTED_CORE_TOOLS = [
    "get_agentos_config",
    "get_models",
    "migrate_database",
    "run_agent",
    "run_team",
    "run_workflow",
]

EXPECTED_AGENT_TOOLS = [
    "list_agents",
    "get_agent",
    "cancel_agent_run",
    "continue_agent_run",
]

EXPECTED_TEAM_TOOLS = [
    "list_teams",
    "get_team",
    "cancel_team_run",
]

EXPECTED_WORKFLOW_TOOLS = [
    "list_workflows",
    "get_workflow",
    "cancel_workflow_run",
]

EXPECTED_SESSION_TOOLS = [
    # Full CRUD
    "get_sessions",
    "create_session",
    "get_session",
    "get_session_runs",
    "get_session_run",
    "delete_session",
    "delete_sessions",
    "rename_session",
    "update_session",
    # Legacy convenience tools
    "get_sessions_for_agent",
    "get_sessions_for_team",
    "get_sessions_for_workflow",
]

EXPECTED_MEMORY_TOOLS = [
    "create_memory",
    "get_memories_for_user",
    "get_memory",
    "update_memory",
    "delete_memory",
    "delete_memories",
    "get_memory_topics",
    "get_user_memory_stats",
    "optimize_memories",
]

EXPECTED_KNOWLEDGE_TOOLS = [
    "upload_content",
    "update_content",
    "get_content",
    "get_content_by_id",
    "get_content_status",
    "delete_content_by_id",
    "delete_all_content",
    "search_knowledge",
    "get_knowledge_config",
]

EXPECTED_EVAL_TOOLS = [
    "get_eval_runs",
    "get_eval_run",
    "delete_eval_runs",
    "update_eval_run",
    "run_eval",
]

EXPECTED_METRICS_TOOLS = [
    "get_metrics",
    "refresh_metrics",
]

EXPECTED_TRACES_TOOLS = [
    "get_traces",
    "get_trace",
    "get_trace_stats",
]


# --- Tool Registration Tests ---


@pytest.mark.asyncio
async def test_core_tools_registered(test_agent):
    """Test that core MCP tools are registered."""
    from fastmcp import FastMCP

    from agno.os.mcp.tools.core import register_core_tools

    os = AgentOS(agents=[test_agent], enable_mcp_server=False)
    mcp = FastMCP("test")
    register_core_tools(mcp, os)

    tools = await mcp.get_tools()
    for tool_name in EXPECTED_CORE_TOOLS:
        assert tool_name in tools, f"Core tool '{tool_name}' not registered"


@pytest.mark.asyncio
async def test_session_tools_registered(test_agent):
    """Test that session MCP tools are registered."""
    from fastmcp import FastMCP

    from agno.os.mcp.tools.sessions import register_session_tools

    os = AgentOS(agents=[test_agent], enable_mcp_server=False)
    mcp = FastMCP("test")
    register_session_tools(mcp, os)

    tools = await mcp.get_tools()
    for tool_name in EXPECTED_SESSION_TOOLS:
        assert tool_name in tools, f"Session tool '{tool_name}' not registered"


@pytest.mark.asyncio
async def test_memory_tools_registered(test_agent):
    """Test that memory MCP tools are registered."""
    from fastmcp import FastMCP

    from agno.os.mcp.tools.memory import register_memory_tools

    os = AgentOS(agents=[test_agent], enable_mcp_server=False)
    mcp = FastMCP("test")
    register_memory_tools(mcp, os)

    tools = await mcp.get_tools()
    for tool_name in EXPECTED_MEMORY_TOOLS:
        assert tool_name in tools, f"Memory tool '{tool_name}' not registered"


@pytest.mark.asyncio
async def test_agent_tools_registered(test_agent):
    """Test that agent MCP tools are registered."""
    from fastmcp import FastMCP

    from agno.os.mcp.tools.agents import register_agent_tools

    os = AgentOS(agents=[test_agent], enable_mcp_server=False)
    mcp = FastMCP("test")
    register_agent_tools(mcp, os)

    tools = await mcp.get_tools()
    for tool_name in EXPECTED_AGENT_TOOLS:
        assert tool_name in tools, f"Agent tool '{tool_name}' not registered"


@pytest.mark.asyncio
async def test_team_tools_registered(test_agent):
    """Test that team MCP tools are registered."""
    from fastmcp import FastMCP

    from agno.os.mcp.tools.teams import register_team_tools

    os = AgentOS(agents=[test_agent], enable_mcp_server=False)
    mcp = FastMCP("test")
    register_team_tools(mcp, os)

    tools = await mcp.get_tools()
    for tool_name in EXPECTED_TEAM_TOOLS:
        assert tool_name in tools, f"Team tool '{tool_name}' not registered"


@pytest.mark.asyncio
async def test_workflow_tools_registered(test_agent):
    """Test that workflow MCP tools are registered."""
    from fastmcp import FastMCP

    from agno.os.mcp.tools.workflows import register_workflow_tools

    os = AgentOS(agents=[test_agent], enable_mcp_server=False)
    mcp = FastMCP("test")
    register_workflow_tools(mcp, os)

    tools = await mcp.get_tools()
    for tool_name in EXPECTED_WORKFLOW_TOOLS:
        assert tool_name in tools, f"Workflow tool '{tool_name}' not registered"


@pytest.mark.asyncio
async def test_knowledge_tools_registered(test_agent):
    """Test that knowledge MCP tools are registered."""
    from fastmcp import FastMCP

    from agno.os.mcp.tools.knowledge import register_knowledge_tools

    os = AgentOS(agents=[test_agent], enable_mcp_server=False)
    mcp = FastMCP("test")
    register_knowledge_tools(mcp, os)

    tools = await mcp.get_tools()
    for tool_name in EXPECTED_KNOWLEDGE_TOOLS:
        assert tool_name in tools, f"Knowledge tool '{tool_name}' not registered"


@pytest.mark.asyncio
async def test_eval_tools_registered(test_agent):
    """Test that eval MCP tools are registered."""
    from fastmcp import FastMCP

    from agno.os.mcp.tools.evals import register_eval_tools

    os = AgentOS(agents=[test_agent], enable_mcp_server=False)
    mcp = FastMCP("test")
    register_eval_tools(mcp, os)

    tools = await mcp.get_tools()
    for tool_name in EXPECTED_EVAL_TOOLS:
        assert tool_name in tools, f"Eval tool '{tool_name}' not registered"


@pytest.mark.asyncio
async def test_metrics_tools_registered(test_agent):
    """Test that metrics MCP tools are registered."""
    from fastmcp import FastMCP

    from agno.os.mcp.tools.metrics import register_metrics_tools

    os = AgentOS(agents=[test_agent], enable_mcp_server=False)
    mcp = FastMCP("test")
    register_metrics_tools(mcp, os)

    tools = await mcp.get_tools()
    for tool_name in EXPECTED_METRICS_TOOLS:
        assert tool_name in tools, f"Metrics tool '{tool_name}' not registered"


@pytest.mark.asyncio
async def test_traces_tools_registered(test_agent):
    """Test that traces MCP tools are registered."""
    from fastmcp import FastMCP

    from agno.os.mcp.tools.traces import register_traces_tools

    os = AgentOS(agents=[test_agent], enable_mcp_server=False)
    mcp = FastMCP("test")
    register_traces_tools(mcp, os)

    tools = await mcp.get_tools()
    for tool_name in EXPECTED_TRACES_TOOLS:
        assert tool_name in tools, f"Traces tool '{tool_name}' not registered"


@pytest.mark.asyncio
async def test_all_tools_registered(test_agent):
    """Test that all tools are registered together."""
    from fastmcp import FastMCP

    from agno.os.mcp.tools import (
        register_agent_tools,
        register_core_tools,
        register_eval_tools,
        register_knowledge_tools,
        register_memory_tools,
        register_metrics_tools,
        register_session_tools,
        register_team_tools,
        register_traces_tools,
        register_workflow_tools,
    )

    os = AgentOS(agents=[test_agent], enable_mcp_server=False)
    mcp = FastMCP("test")

    register_core_tools(mcp, os)
    register_agent_tools(mcp, os)
    register_team_tools(mcp, os)
    register_workflow_tools(mcp, os)
    register_session_tools(mcp, os)
    register_memory_tools(mcp, os)
    register_knowledge_tools(mcp, os)
    register_eval_tools(mcp, os)
    register_metrics_tools(mcp, os)
    register_traces_tools(mcp, os)

    tools = await mcp.get_tools()
    all_expected = (
        EXPECTED_CORE_TOOLS
        + EXPECTED_AGENT_TOOLS
        + EXPECTED_TEAM_TOOLS
        + EXPECTED_WORKFLOW_TOOLS
        + EXPECTED_SESSION_TOOLS
        + EXPECTED_MEMORY_TOOLS
        + EXPECTED_KNOWLEDGE_TOOLS
        + EXPECTED_EVAL_TOOLS
        + EXPECTED_METRICS_TOOLS
        + EXPECTED_TRACES_TOOLS
    )

    for tool_name in all_expected:
        assert tool_name in tools, f"Tool '{tool_name}' not registered"

    assert len(tools) == len(all_expected), f"Expected {len(all_expected)} tools, got {len(tools)}"


# --- Auth Middleware Tests ---


@pytest.mark.asyncio
async def test_mcp_auth_middleware_allows_request_without_security_key():
    """Test that requests pass through when no security key is configured."""
    from starlette.applications import Starlette
    from starlette.responses import Response
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from agno.os.mcp.server import MCPAuthMiddleware
    from agno.os.settings import AgnoAPISettings

    async def homepage(request):
        return Response("OK")

    # Setup dummy app with no auth requirements. The middleware should just allow requests.
    app = Starlette(routes=[Route("/", homepage)])
    settings = AgnoAPISettings()
    app.add_middleware(MCPAuthMiddleware, settings=settings)

    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert response.text == "OK"


@pytest.mark.asyncio
async def test_mcp_auth_middleware_rejects_bad_requests():
    """Test that requests without Authorization header are rejected when security is enabled."""
    from starlette.applications import Starlette
    from starlette.responses import Response
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from agno.os.mcp.server import MCPAuthMiddleware
    from agno.os.settings import AgnoAPISettings

    async def homepage(request):
        return Response("OK")

    # Setup dummy app with auth requirements.
    app = Starlette(routes=[Route("/", homepage)])
    settings = AgnoAPISettings(os_security_key="test-secret-key")
    app.add_middleware(MCPAuthMiddleware, settings=settings)

    # The middleware should reject requests without the Authorization header.
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 401
    assert "Authorization header required" in response.json()["detail"]

    # The middleware should reject requests with an invalid token.
    client = TestClient(app)
    response = client.get("/", headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401
    assert "Invalid authentication token" in response.json()["detail"]


@pytest.mark.asyncio
async def test_mcp_auth_middleware_accepts_valid_token():
    """Test that requests with valid token are accepted."""
    from starlette.applications import Starlette
    from starlette.responses import Response
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from agno.os.mcp.server import MCPAuthMiddleware
    from agno.os.settings import AgnoAPISettings

    async def homepage(request):
        return Response("OK")

    # Setup dummy app with auth requirements.
    app = Starlette(routes=[Route("/", homepage)])
    settings = AgnoAPISettings(os_security_key="test-secret-key")
    app.add_middleware(MCPAuthMiddleware, settings=settings)

    # The middleware should accept requests with the correct token.
    client = TestClient(app)
    response = client.get("/", headers={"Authorization": "Bearer test-secret-key"})

    assert response.status_code == 200
    assert response.text == "OK"
