"""Integration tests for MCP server tools in AgentOS.

These tests verify that MCP tools are properly registered and auth works correctly.
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
    "get_sessions",
    "create_session",
    "get_session",
    "get_session_runs",
    "get_session_run",
    "delete_session",
    "delete_sessions",
    "rename_session",
    "update_session",
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

ALL_EXPECTED_TOOLS = (
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


# --- Tool Registration Tests ---


@pytest.mark.asyncio
async def test_all_tools_registered(test_agent):
    """Test that all MCP tools are registered via get_mcp_server."""
    from agno.os.mcp.server import get_mcp_server

    os = AgentOS(agents=[test_agent], enable_mcp_server=False)
    mcp_app = get_mcp_server(os)

    # Access the underlying FastMCP instance to check tools
    # The mcp_app wraps FastMCP, we need to get tools from it
    assert mcp_app is not None

    # Verify by checking the app has routes (MCP endpoints)
    assert len(mcp_app.routes) > 0


@pytest.mark.asyncio
async def test_tool_registration_via_modules(test_agent):
    """Test that all tools are properly registered when using register functions directly."""
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

    # Check all expected tools are registered
    for tool_name in ALL_EXPECTED_TOOLS:
        assert tool_name in tools, f"Tool '{tool_name}' not registered"

    # Check we have exactly the expected number of tools
    assert len(tools) == len(ALL_EXPECTED_TOOLS), f"Expected {len(ALL_EXPECTED_TOOLS)} tools, got {len(tools)}"


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

    app = Starlette(routes=[Route("/", homepage)])
    settings = AgnoAPISettings()
    app.add_middleware(MCPAuthMiddleware, settings=settings)

    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert response.text == "OK"


@pytest.mark.asyncio
async def test_mcp_auth_middleware_rejects_bad_requests():
    """Test that requests are rejected when security is enabled but token is missing/invalid."""
    from starlette.applications import Starlette
    from starlette.responses import Response
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from agno.os.mcp.server import MCPAuthMiddleware
    from agno.os.settings import AgnoAPISettings

    async def homepage(request):
        return Response("OK")

    app = Starlette(routes=[Route("/", homepage)])
    settings = AgnoAPISettings(os_security_key="test-secret-key")
    app.add_middleware(MCPAuthMiddleware, settings=settings)

    client = TestClient(app)

    # Missing header
    response = client.get("/")
    assert response.status_code == 401
    assert "Authorization header required" in response.json()["detail"]

    # Invalid token
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

    app = Starlette(routes=[Route("/", homepage)])
    settings = AgnoAPISettings(os_security_key="test-secret-key")
    app.add_middleware(MCPAuthMiddleware, settings=settings)

    client = TestClient(app)
    response = client.get("/", headers={"Authorization": "Bearer test-secret-key"})

    assert response.status_code == 200
    assert response.text == "OK"


# --- Auth Helper Tests ---


def test_auth_helpers_without_authorization():
    """Test auth helpers return permissive values when authorization is disabled."""
    from unittest.mock import MagicMock

    from agno.os.mcp.auth import (
        check_resource_access,
        filter_agents_by_access,
        is_authorization_enabled,
    )

    ctx = MagicMock()
    ctx.request_context = MagicMock()
    ctx.request_context.request = MagicMock()
    ctx.request_context.request.state = MagicMock()
    ctx.request_context.request.state.authorization_enabled = False

    # Should allow everything when authorization is disabled
    assert is_authorization_enabled(ctx) is False
    assert check_resource_access(ctx, "any-agent-id", "agents") is True

    # Filter should return all agents
    mock_agents = [MagicMock(id="agent-1"), MagicMock(id="agent-2")]
    filtered = filter_agents_by_access(ctx, mock_agents)
    assert len(filtered) == 2


def test_auth_helpers_with_limited_access():
    """Test auth helpers correctly filter resources based on scopes."""
    from unittest.mock import MagicMock, patch

    from agno.os.mcp.auth import check_resource_access, filter_agents_by_access

    ctx = MagicMock()
    ctx.request_context = MagicMock()
    ctx.request_context.request = MagicMock()
    ctx.request_context.request.state = MagicMock()
    ctx.request_context.request.state.authorization_enabled = True
    ctx.request_context.request.state.scopes = ["agents:agent-1:read"]
    ctx.request_context.request.state.accessible_resource_ids = None

    with patch("agno.os.mcp.auth.get_accessible_resource_ids") as mock_get_ids:
        mock_get_ids.return_value = {"agent-1"}

        # Should allow access to agent-1 but not agent-2
        assert check_resource_access(ctx, "agent-1", "agents") is True
        assert check_resource_access(ctx, "agent-2", "agents") is False

        # Filter should only return agent-1
        mock_agents = [MagicMock(id="agent-1"), MagicMock(id="agent-2")]
        filtered = filter_agents_by_access(ctx, mock_agents)
        assert len(filtered) == 1
        assert filtered[0].id == "agent-1"


def test_require_resource_access_raises_on_denied():
    """Test require_resource_access raises exception when access is denied."""
    from unittest.mock import MagicMock, patch

    from agno.os.mcp.auth import require_resource_access

    ctx = MagicMock()
    ctx.request_context = MagicMock()
    ctx.request_context.request = MagicMock()
    ctx.request_context.request.state = MagicMock()
    ctx.request_context.request.state.authorization_enabled = True
    ctx.request_context.request.state.scopes = ["agents:agent-1:read"]
    ctx.request_context.request.state.accessible_resource_ids = None

    with patch("agno.os.mcp.auth.get_accessible_resource_ids") as mock_get_ids:
        mock_get_ids.return_value = {"agent-1"}

        # Should not raise for agent-1
        require_resource_access(ctx, "agent-1", "agents")

        # Should raise for agent-2
        with pytest.raises(Exception, match="Access denied"):
            require_resource_access(ctx, "agent-2", "agents")
