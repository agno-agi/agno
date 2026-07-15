"""
Comprehensive System Tests for MCP (Model Context Protocol) Routes.

These tests verify the MCP interface functionality provided by AgentOS.
The MCP server exposes tools that can be called by MCP clients using
Streamable HTTP transport (the modern MCP standard).

Coverage:
- Connection and authentication
- Configuration and tool discovery
- Running agents (local and remote)
- Running teams (remote)
- Running workflows (local and remote)
- Session management for agents, teams, and workflows
- Memory management (CRUD operations)
- Error handling

Run with: pytest test_mcp_routes.py -v --tb=short

Note: These tests require the MCP server to be enabled on the gateway
and require both gateway and remote servers to be running.
"""

import json
import uuid
from datetime import timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

import pytest

# Skip all tests if mcp is not installed
pytest.importorskip("mcp")

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .test_utils import REQUEST_TIMEOUT, generate_jwt_token


class MCPTestClient:
    """A test client for interacting with MCP servers."""

    def __init__(self, url: str, headers: Optional[Dict[str, str]] = None):
        self.url = url
        self.headers = headers or {}
        self.session: Optional[ClientSession] = None
        self._context = None
        self._session_context = None
        self._active_contexts = []

    async def connect(self):
        """Connect to the MCP server."""
        try:
            # Create streamable HTTP client with timeout
            self._context = streamablehttp_client(
                url=self.url,
                headers=self.headers,
                timeout=timedelta(seconds=REQUEST_TIMEOUT),
                sse_read_timeout=timedelta(seconds=REQUEST_TIMEOUT),
            )
            session_params = await self._context.__aenter__()
            self._active_contexts.append(self._context)
            # streamablehttp_client returns a tuple of (read, write, session_id_callable)
            read, write, _ = session_params

            # Create client session with timeout
            self._session_context = ClientSession(read, write, read_timeout_seconds=timedelta(seconds=REQUEST_TIMEOUT))
            self.session = await self._session_context.__aenter__()
            self._active_contexts.append(self._session_context)

            # Initialize the session (MCP handshake)
            await self.session.initialize()
        except Exception as e:
            # Clean up on connection failure
            await self.close()
            raise Exception(f"Failed to connect to MCP server at {self.url}: {e}")

    async def close(self):
        """Close the connection."""
        # Close contexts in reverse order of creation
        errors = []

        if self._session_context:
            try:
                await self._session_context.__aexit__(None, None, None)
            except Exception as e:
                errors.append(f"Session context cleanup error: {e}")
            finally:
                self.session = None
                self._session_context = None

        if self._context:
            try:
                await self._context.__aexit__(None, None, None)
            except Exception as e:
                errors.append(f"HTTP context cleanup error: {e}")
            finally:
                self._context = None

        if errors:
            print(f"Errors during close: {'; '.join(errors)}")

    async def list_tools(self) -> List[str]:
        """List available tools on the MCP server."""
        if not self.session:
            raise RuntimeError("Not connected")
        result = await self.session.list_tools()
        return [tool.name for tool in result.tools]

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Call a tool on the MCP server and return the result."""
        if not self.session:
            raise RuntimeError("Not connected")
        result = await self.session.call_tool(tool_name, arguments)
        if result.isError:
            raise Exception(f"Tool call failed: {result.content}")

        # Parse the response
        response_parts = []
        for content_item in result.content:
            if hasattr(content_item, "text"):
                text = content_item.text
                try:
                    # Try to parse as JSON
                    response_parts.append(json.loads(text))
                except json.JSONDecodeError:
                    response_parts.append(text)

        if len(response_parts) == 1:
            return response_parts[0]
        return response_parts


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def test_user_id() -> str:
    """Generate a unique user ID for testing."""
    return f"U{uuid.uuid4().hex[:8].upper()}"


@pytest.fixture(scope="module")
def mcp_url(gateway_url: str) -> str:
    """Get the MCP server URL."""
    return f"{gateway_url}/mcp"


# Removed custom event_loop fixture - using pytest-asyncio's default
# The default fixture properly handles the event loop lifecycle


@pytest.fixture
async def mcp_client(mcp_url: str, test_user_id: str):
    """Create and connect an MCP client."""
    headers = {"Authorization": f"Bearer {generate_jwt_token(audience='gateway-os', user_id=test_user_id)}"}
    client = MCPTestClient(mcp_url, headers=headers)
    try:
        await client.connect()
        yield client
    finally:
        await client.close()


@pytest.fixture(scope="module")
def db_id() -> str:
    """Get the database ID for testing."""
    return "gateway-db"


@pytest.fixture
def test_session_id() -> str:
    """Generate a unique session ID for testing."""
    return str(uuid.uuid4())


# =============================================================================
# Connection Tests
# =============================================================================


@pytest.mark.asyncio
async def test_mcp_connection(mcp_client: MCPTestClient):
    """Test that we can connect to the MCP server."""
    assert mcp_client.session is not None
    # Verify we can ping the server
    await mcp_client.session.send_ping()


@pytest.mark.asyncio
async def test_list_tools(mcp_client: MCPTestClient):
    """Test listing available MCP tools."""
    tools = await mcp_client.list_tools()
    assert isinstance(tools, list)
    assert len(tools) > 0

    # Check for expected core tools
    expected_tools = [
        "get_agentos_config",
        "run_agent",
        "run_team",
        "run_workflow",
        "continue_run",
        "cancel_run",
        "get_sessions",
        "get_session_runs",
    ]
    for tool_name in expected_tools:
        assert tool_name in tools, f"Missing expected tool: {tool_name}"

    # The v2.7 surface is deliberately trimmed: session writes and memory CRUD are gone.
    removed_tools = [
        "get_session",
        "create_session",
        "update_session",
        "rename_session",
        "delete_session",
        "delete_sessions",
        "create_memory",
        "get_memory",
        "get_memories",
        "update_memory",
        "delete_memory",
        "delete_memories",
    ]
    for tool_name in removed_tools:
        assert tool_name not in tools, f"Removed tool still present: {tool_name}"


# =============================================================================
# Core Tools Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_agentos_config(mcp_client: MCPTestClient):
    """Test the get_agentos_config tool."""
    result = await mcp_client.call_tool("get_agentos_config", {})

    # The v2.7 config tool is a compact discovery payload: ids/summaries + db ids only.
    assert "os_id" in result
    assert result["os_id"] == "gateway-os"
    assert "agents" in result
    assert "teams" in result
    assert "workflows" in result
    assert "databases" in result
    # Heavy per-domain config sections are intentionally not in the MCP payload (REST /config only).
    for heavy_key in ("interfaces", "learning", "memory", "knowledge", "evals", "metrics", "traces"):
        assert heavy_key not in result, f"Compact config must not include '{heavy_key}'"

    # Verify both local and remote agents are present
    agent_ids = [agent["id"] for agent in result["agents"]]
    assert "gateway-agent" in agent_ids, "Local agent 'gateway-agent' should be present"
    assert "assistant-agent" in agent_ids, "Remote agent 'assistant-agent' should be present"
    assert "researcher-agent" in agent_ids, "Remote agent 'researcher-agent' should be present"

    # Verify teams are present
    team_ids = [team["id"] for team in result["teams"]]
    assert "research-team" in team_ids, "Remote team 'research-team' should be present"

    # Verify workflows are present
    workflow_ids = [workflow["id"] for workflow in result["workflows"]]
    assert "gateway-workflow" in workflow_ids, "Local workflow 'gateway-workflow' should be present"
    assert "qa-workflow" in workflow_ids, "Remote workflow 'qa-workflow' should be present"


@pytest.mark.asyncio
async def test_run_agent(mcp_client: MCPTestClient):
    """Test running a local agent via MCP."""
    result = await mcp_client.call_tool(
        "run_agent",
        {
            "agent_id": "gateway-agent",
            "message": "Say hello in exactly 5 words",
        },
    )

    # Check the result has expected fields
    assert result is not None
    # Trimmed result: the text block is the answer itself (a plain string unless the
    # answer happens to be JSON); structured ids live in structuredContent.
    assert isinstance(result, str) or (isinstance(result, dict) and ("content" in result or "run_id" in result))


@pytest.mark.asyncio
async def test_run_remote_agent(mcp_client: MCPTestClient):
    """Test running a remote agent via MCP."""
    result = await mcp_client.call_tool(
        "run_agent",
        {
            "agent_id": "assistant-agent",
            "message": "Say hello in exactly 5 words",
        },
    )

    # Check the result has expected fields
    assert result is not None
    # Trimmed result: the text block is the answer itself (a plain string unless the
    # answer happens to be JSON); structured ids live in structuredContent.
    assert isinstance(result, str) or (isinstance(result, dict) and ("content" in result or "run_id" in result))


@pytest.mark.asyncio
async def test_run_remote_team(mcp_client: MCPTestClient):
    """Test running a remote team via MCP."""
    result = await mcp_client.call_tool(
        "run_team",
        {
            "team_id": "research-team",
            "message": "What is the capital of France?",
        },
    )

    # Check the result has expected fields
    assert result is not None
    # Trimmed result: the text block is the answer itself (a plain string unless the
    # answer happens to be JSON); structured ids live in structuredContent.
    assert isinstance(result, str) or (isinstance(result, dict) and ("content" in result or "run_id" in result))


@pytest.mark.asyncio
async def test_run_local_workflow(mcp_client: MCPTestClient):
    """Test running a local workflow via MCP."""
    result = await mcp_client.call_tool(
        "run_workflow",
        {
            "workflow_id": "gateway-workflow",
            "message": "Process this message",
        },
    )

    # Check the result has expected fields
    assert result is not None
    # Trimmed result: the text block is the answer itself (a plain string unless the
    # answer happens to be JSON); structured ids live in structuredContent.
    assert isinstance(result, str) or (isinstance(result, dict) and ("content" in result or "run_id" in result))


@pytest.mark.asyncio
async def test_run_remote_workflow(mcp_client: MCPTestClient):
    """Test running a remote workflow via MCP."""
    result = await mcp_client.call_tool(
        "run_workflow",
        {
            "workflow_id": "qa-workflow",
            "message": "Answer this question: What is 2+2?",
        },
    )

    # Check the result has expected fields
    assert result is not None
    # Trimmed result: the text block is the answer itself (a plain string unless the
    # answer happens to be JSON); structured ids live in structuredContent.
    assert isinstance(result, str) or (isinstance(result, dict) and ("content" in result or "run_id" in result))


# =============================================================================
# Session Management Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_sessions(mcp_client: MCPTestClient, db_id: str, test_user_id: str):
    """Test getting sessions via MCP."""
    result = await mcp_client.call_tool(
        "get_sessions",
        {
            "db_id": db_id,
            "session_type": "agent",
            "user_id": test_user_id,
            "limit": 10,
            "page": 1,
        },
    )

    assert "data" in result
    assert "meta" in result
    assert isinstance(result["data"], list)
    assert "page" in result["meta"]
    assert "limit" in result["meta"]
    assert "total_count" in result["meta"]


@pytest.mark.asyncio
async def test_get_session_runs_after_run(mcp_client: MCPTestClient, db_id: str, test_user_id: str):
    """Run an agent into a fresh session, then read the conversation back.

    Exercises the v2.7 read-only session path: run tools create sessions implicitly
    and get_session_runs auto-detects the session type (no session_type passed).
    The gateway registers a second (remote) database, so db_id is passed the way
    an operator would after discovering it via get_agentos_config.
    """
    session_id = str(uuid4())
    await mcp_client.call_tool(
        "run_agent",
        {
            "agent_id": "gateway-agent",
            "message": "Say hello in exactly 3 words",
            "session_id": session_id,
            "user_id": test_user_id,
        },
    )

    result = await mcp_client.call_tool("get_session_runs", {"session_id": session_id, "db_id": db_id})
    runs = result if isinstance(result, list) else [result]
    assert len(runs) >= 1


@pytest.mark.asyncio
async def test_get_session_runs_not_found(mcp_client: MCPTestClient, db_id: str):
    """Reading history of a non-existent session returns a tool error."""
    with pytest.raises(Exception) as exc_info:
        await mcp_client.call_tool("get_session_runs", {"session_id": "non-existent-session", "db_id": db_id})
    assert "not found" in str(exc_info.value).lower()


# =============================================================================
# Traces Tests
# =============================================================================


@pytest.mark.skip(reason="get_traces tool not yet implemented in MCP server")
@pytest.mark.asyncio
async def test_get_traces(mcp_client: MCPTestClient, db_id: str):
    """Test getting traces via MCP."""
    result = await mcp_client.call_tool(
        "get_traces",
        {
            "db_id": db_id,
            "limit": 10,
            "page": 1,
        },
    )

    assert "data" in result
    assert "meta" in result
    assert isinstance(result["data"], list)


@pytest.mark.skip(reason="get_trace_session_stats tool not yet implemented in MCP server")
@pytest.mark.asyncio
async def test_get_trace_session_stats(mcp_client: MCPTestClient, db_id: str):
    """Test getting trace session statistics via MCP."""
    result = await mcp_client.call_tool(
        "get_trace_session_stats",
        {
            "db_id": db_id,
            "limit": 10,
            "page": 1,
        },
    )

    assert "data" in result
    assert "meta" in result
    assert isinstance(result["data"], list)


# =============================================================================
# Evals Tests
# =============================================================================


@pytest.mark.skip(reason="get_eval_runs tool not yet implemented in MCP server")
@pytest.mark.asyncio
async def test_get_eval_runs(mcp_client: MCPTestClient, db_id: str):
    """Test getting eval runs via MCP."""
    result = await mcp_client.call_tool(
        "get_eval_runs",
        {
            "db_id": db_id,
            "limit": 10,
            "page": 1,
        },
    )

    assert "data" in result
    assert "meta" in result
    assert isinstance(result["data"], list)


# =============================================================================
# Metrics Tests
# =============================================================================


@pytest.mark.skip(reason="get_metrics tool not yet implemented in MCP server")
@pytest.mark.asyncio
async def test_get_metrics(mcp_client: MCPTestClient, db_id: str):
    """Test getting metrics via MCP."""
    result = await mcp_client.call_tool(
        "get_metrics",
        {
            "db_id": db_id,
        },
    )

    assert result is not None
    assert "metrics" in result


@pytest.mark.skip(reason="refresh_metrics tool not yet implemented in MCP server")
@pytest.mark.asyncio
async def test_refresh_metrics(mcp_client: MCPTestClient, db_id: str):
    """Test refreshing metrics via MCP."""
    result = await mcp_client.call_tool(
        "refresh_metrics",
        {
            "db_id": db_id,
        },
    )

    assert result is not None
    assert isinstance(result, list)


# =============================================================================
# Cleanup Tests (run at the end)
# =============================================================================


# =============================================================================
# Error Handling Tests
# =============================================================================


@pytest.mark.asyncio
async def test_run_agent_not_found(mcp_client: MCPTestClient):
    """Test running a non-existent agent returns appropriate error."""
    with pytest.raises(Exception) as exc_info:
        await mcp_client.call_tool(
            "run_agent",
            {
                "agent_id": "non-existent-agent",
                "message": "Hello",
            },
        )
    assert "not found" in str(exc_info.value).lower()
