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
        "get_sessions",
        "get_session",
        "create_session",
        "create_memory",
        "get_memories",
    ]
    for tool_name in expected_tools:
        assert tool_name in tools, f"Missing expected tool: {tool_name}"


# =============================================================================
# Core Tools Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_agentos_config(mcp_client: MCPTestClient):
    """Test the get_agentos_config tool."""
    result = await mcp_client.call_tool("get_agentos_config", {})

    assert "os_id" in result
    assert result["os_id"] == "gateway-os"
    assert "agents" in result
    assert "teams" in result
    assert "workflows" in result
    assert "interfaces" in result
    assert "databases" in result

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
    # The result should be a RunOutput with content
    assert "content" in result or isinstance(result, str)


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
    # The result should be a RunOutput with content
    assert "content" in result or isinstance(result, str)


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
    # The result should be a TeamRunOutput with content
    assert "content" in result or isinstance(result, str)


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
    # The result should be a WorkflowRunOutput with content
    assert "content" in result or isinstance(result, str)


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
    # The result should be a WorkflowRunOutput with content
    assert "content" in result or isinstance(result, str)


# =============================================================================
# Session Management Tests
# =============================================================================


@pytest.mark.asyncio
async def test_create_session(mcp_client: MCPTestClient, db_id: str, test_session_id: str, test_user_id: str):
    """Test creating a new session with a local agent via MCP."""
    result = await mcp_client.call_tool(
        "create_session",
        {
            "db_id": db_id,
            "session_type": "agent",
            "session_id": test_session_id,
            "session_name": "MCP Test Session",
            "user_id": test_user_id,
            "agent_id": "gateway-agent",
            "session_state": {"test_key": "test_value"},
        },
    )

    assert result is not None
    assert result.get("session_id") == test_session_id
    assert result.get("session_name") == "MCP Test Session"


@pytest.mark.asyncio
async def test_create_session_remote_agent(mcp_client: MCPTestClient, db_id: str, test_user_id: str):
    """Test creating a new session with a remote agent via MCP."""
    remote_session_id = str(uuid4())
    result = await mcp_client.call_tool(
        "create_session",
        {
            "db_id": db_id,
            "session_type": "agent",
            "session_id": remote_session_id,
            "session_name": "MCP Remote Agent Test Session",
            "user_id": test_user_id,
            "agent_id": "assistant-agent",
            "session_state": {"remote_test": True},
        },
    )

    assert result is not None
    assert result.get("session_id") == remote_session_id
    assert result.get("session_name") == "MCP Remote Agent Test Session"
    assert result.get("agent_id") == "assistant-agent"


@pytest.mark.asyncio
async def test_create_session_remote_team(mcp_client: MCPTestClient, db_id: str, test_user_id: str):
    """Test creating a new session with a remote team via MCP."""
    team_session_id = str(uuid4())
    result = await mcp_client.call_tool(
        "create_session",
        {
            "db_id": db_id,
            "session_type": "team",
            "session_id": team_session_id,
            "session_name": "MCP Team Test Session",
            "user_id": test_user_id,
            "team_id": "research-team",
            "session_state": {"team_test": True},
        },
    )

    assert result is not None
    assert result.get("session_id") == team_session_id
    assert result.get("session_name") == "MCP Team Test Session"
    assert result.get("team_id") == "research-team"


@pytest.mark.asyncio
async def test_create_session_local_workflow(mcp_client: MCPTestClient, db_id: str, test_user_id: str):
    """Test creating a new session with a local workflow via MCP."""
    workflow_session_id = str(uuid4())
    result = await mcp_client.call_tool(
        "create_session",
        {
            "db_id": db_id,
            "session_type": "workflow",
            "session_id": workflow_session_id,
            "session_name": "MCP Local Workflow Test Session",
            "user_id": test_user_id,
            "workflow_id": "gateway-workflow",
            "session_state": {"workflow_test": True},
        },
    )

    assert result is not None
    assert result.get("session_id") == workflow_session_id
    assert result.get("session_name") == "MCP Local Workflow Test Session"
    assert result.get("workflow_id") == "gateway-workflow"


@pytest.mark.asyncio
async def test_create_session_remote_workflow(mcp_client: MCPTestClient, db_id: str, test_user_id: str):
    """Test creating a new session with a remote workflow via MCP."""
    workflow_session_id = str(uuid4())
    result = await mcp_client.call_tool(
        "create_session",
        {
            "db_id": db_id,
            "session_type": "workflow",
            "session_id": workflow_session_id,
            "session_name": "MCP Remote Workflow Test Session",
            "user_id": test_user_id,
            "workflow_id": "qa-workflow",
            "session_state": {"remote_workflow_test": True},
        },
    )

    assert result is not None
    assert result.get("session_id") == workflow_session_id
    assert result.get("session_name") == "MCP Remote Workflow Test Session"
    assert result.get("workflow_id") == "qa-workflow"


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
async def test_get_session(mcp_client: MCPTestClient, db_id: str, test_user_id: str):
    """Test getting a specific session via MCP."""
    # First create a session
    session_id = str(uuid4())
    await mcp_client.call_tool(
        "create_session",
        {
            "db_id": db_id,
            "session_type": "agent",
            "session_id": session_id,
            "session_name": "Get Session Test",
            "user_id": test_user_id,
            "agent_id": "gateway-agent",
        },
    )

    # Then get it
    result = await mcp_client.call_tool(
        "get_session",
        {
            "session_id": session_id,
            "db_id": db_id,
            "session_type": "agent",
        },
    )

    assert result is not None
    assert result.get("session_id") == session_id


@pytest.mark.asyncio
async def test_rename_session(mcp_client: MCPTestClient, db_id: str, test_user_id: str):
    """Test renaming a session via MCP."""
    # First create a session
    session_id = str(uuid4())
    await mcp_client.call_tool(
        "create_session",
        {
            "db_id": db_id,
            "session_type": "agent",
            "session_id": session_id,
            "session_name": "Original Name",
            "user_id": test_user_id,
            "agent_id": "gateway-agent",
        },
    )

    # Then rename it
    new_name = "Renamed MCP Test Session"
    result = await mcp_client.call_tool(
        "rename_session",
        {
            "session_id": session_id,
            "session_name": new_name,
            "db_id": db_id,
            "session_type": "agent",
        },
    )

    assert result is not None
    assert result.get("session_name") == new_name


@pytest.mark.asyncio
async def test_update_session(mcp_client: MCPTestClient, db_id: str, test_user_id: str):
    """Test updating a session via MCP."""
    # First create a session
    session_id = str(uuid4())
    await mcp_client.call_tool(
        "create_session",
        {
            "db_id": db_id,
            "session_type": "agent",
            "session_id": session_id,
            "session_name": "Update Test Session",
            "user_id": test_user_id,
            "agent_id": "gateway-agent",
        },
    )

    # Then update it
    result = await mcp_client.call_tool(
        "update_session",
        {
            "session_id": session_id,
            "db_id": db_id,
            "session_type": "agent",
            "session_state": {"updated_key": "updated_value"},
            "metadata": {"meta_key": "meta_value"},
        },
    )

    assert result is not None
    assert result.get("session_state", {}).get("updated_key") == "updated_value"


# =============================================================================
# Memory Management Tests
# =============================================================================


@pytest.fixture
def test_memory_id() -> str:
    """Generate a unique memory ID for testing."""
    return str(uuid.uuid4())


@pytest.mark.asyncio
async def test_create_memory(mcp_client: MCPTestClient, db_id: str, test_user_id: str):
    """Test creating a memory via MCP."""
    result = await mcp_client.call_tool(
        "create_memory",
        {
            "db_id": db_id,
            "memory": "This is a test memory created via MCP",
            "user_id": test_user_id,
            "topics": ["test", "mcp"],
        },
    )

    assert result is not None
    assert "memory_id" in result
    assert result.get("memory") == "This is a test memory created via MCP"
    assert result.get("user_id") == test_user_id

    # Store memory_id for later tests
    return result.get("memory_id")


@pytest.mark.asyncio
async def test_get_memories(mcp_client: MCPTestClient, db_id: str, test_user_id: str):
    """Test getting memories via MCP."""
    result = await mcp_client.call_tool(
        "get_memories",
        {
            "db_id": db_id,
            "user_id": test_user_id,
            "limit": 10,
            "page": 1,
        },
    )

    assert "data" in result
    assert "meta" in result
    assert isinstance(result["data"], list)


@pytest.mark.asyncio
async def test_update_memory(mcp_client: MCPTestClient, db_id: str, test_user_id: str):
    """Test updating a memory via MCP."""
    # First create a memory
    create_result = await mcp_client.call_tool(
        "create_memory",
        {
            "db_id": db_id,
            "memory": "Original memory content",
            "user_id": test_user_id,
            "topics": ["original"],
        },
    )
    memory_id = create_result.get("memory_id")

    # Then update it
    result = await mcp_client.call_tool(
        "update_memory",
        {
            "db_id": db_id,
            "memory_id": memory_id,
            "memory": "Updated memory content",
            "user_id": test_user_id,
            "topics": ["updated"],
        },
    )

    assert result is not None
    assert result.get("memory") == "Updated memory content"


@pytest.mark.asyncio
async def test_get_memory(mcp_client: MCPTestClient, db_id: str, test_user_id: str):
    """Test getting a specific memory via MCP."""
    # First create a memory
    create_result = await mcp_client.call_tool(
        "create_memory",
        {
            "db_id": db_id,
            "memory": "Memory to retrieve",
            "user_id": test_user_id,
        },
    )
    memory_id = create_result.get("memory_id")

    # Then get it
    result = await mcp_client.call_tool(
        "get_memory",
        {
            "memory_id": memory_id,
            "db_id": db_id,
        },
    )

    assert result is not None
    assert result.get("memory_id") == memory_id
    assert result.get("memory") == "Memory to retrieve"


@pytest.mark.asyncio
async def test_delete_memory(mcp_client: MCPTestClient, db_id: str, test_user_id: str):
    """Test deleting a memory via MCP."""
    # First create a memory
    create_result = await mcp_client.call_tool(
        "create_memory",
        {
            "db_id": db_id,
            "memory": "Memory to delete",
            "user_id": test_user_id,
        },
    )
    memory_id = create_result.get("memory_id")

    # Delete it
    result = await mcp_client.call_tool(
        "delete_memory",
        {
            "db_id": db_id,
            "memory_id": memory_id,
        },
    )

    # Result should indicate successful deletion
    assert result is not None
    assert "deleted successfully" in result.lower() or result in ["", "null", None]


@pytest.mark.asyncio
async def test_delete_memories_bulk(mcp_client: MCPTestClient, db_id: str, test_user_id: str):
    """Test bulk deleting memories via MCP."""
    # Create multiple memories
    memory_ids = []
    for i in range(3):
        create_result = await mcp_client.call_tool(
            "create_memory",
            {
                "db_id": db_id,
                "memory": f"Bulk delete memory {i}",
                "user_id": test_user_id,
            },
        )
        memory_ids.append(create_result.get("memory_id"))

    # Delete them in bulk
    result = await mcp_client.call_tool(
        "delete_memories",
        {
            "memory_ids": memory_ids,
            "db_id": db_id,
        },
    )

    # Result should indicate successful deletion
    assert result is not None
    assert "deleted successfully" in result.lower() or result in ["", "null", None]


@pytest.mark.skip(reason="get_user_memory_stats tool not yet implemented in MCP server")
@pytest.mark.asyncio
async def test_get_user_memory_stats(mcp_client: MCPTestClient, db_id: str):
    """Test getting user memory statistics via MCP."""
    result = await mcp_client.call_tool(
        "get_user_memory_stats",
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


@pytest.mark.asyncio
async def test_cleanup_delete_session(mcp_client: MCPTestClient, db_id: str, test_user_id: str):
    """Clean up: delete the test session."""
    # Create a session to delete
    session_id = str(uuid4())
    await mcp_client.call_tool(
        "create_session",
        {
            "db_id": db_id,
            "session_type": "agent",
            "session_id": session_id,
            "user_id": test_user_id,
            "agent_id": "gateway-agent",
        },
    )

    # Delete it
    result = await mcp_client.call_tool(
        "delete_session",
        {
            "session_id": session_id,
            "db_id": db_id,
        },
    )

    # Result should indicate successful deletion
    assert result is not None
    assert "deleted successfully" in result.lower() or result in ["", "null", None]


# =============================================================================
# Error Handling Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_session_not_found(mcp_client: MCPTestClient, db_id: str):
    """Test getting a non-existent session returns appropriate error."""
    with pytest.raises(Exception) as exc_info:
        await mcp_client.call_tool(
            "get_session",
            {
                "session_id": "non-existent-session-id",
                "db_id": db_id,
                "session_type": "agent",
            },
        )
    assert "not found" in str(exc_info.value).lower()


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


@pytest.mark.asyncio
async def test_get_memory_not_found(mcp_client: MCPTestClient, db_id: str):
    """Test getting a non-existent memory returns appropriate error."""
    with pytest.raises(Exception) as exc_info:
        await mcp_client.call_tool(
            "get_memory",
            {
                "memory_id": "non-existent-memory-id",
                "db_id": db_id,
            },
        )
    assert "not found" in str(exc_info.value).lower()
