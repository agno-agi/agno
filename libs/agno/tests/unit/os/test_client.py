"""
Unit tests for AgentOSClient.

Tests cover:
1. Client initialization and configuration
2. Context manager functionality
3. HTTP method helpers
4. Discovery operations
5. Memory operations
6. Session operations
7. Eval operations
8. Knowledge operations
9. Run operations
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Set test environment variables
os.environ.setdefault("AGNO_API_KEY", "test-api-key")

from agno.os.client import AgentOSClient


def test_init_with_base_url():
    """Verify basic initialization with base URL."""
    client = AgentOSClient(base_url="http://localhost:7777")
    assert client.base_url == "http://localhost:7777"
    assert client.timeout == 60.0
    assert client._http_client is None


def test_init_strips_trailing_slash():
    """Verify trailing slash is removed from base URL."""
    client = AgentOSClient(base_url="http://localhost:7777/")
    assert client.base_url == "http://localhost:7777"


def test_init_with_custom_timeout():
    """Verify custom timeout is respected."""
    client = AgentOSClient(base_url="http://localhost:7777", timeout=60.0)
    assert client.timeout == 60.0


def test_init_with_api_key():
    """Verify API key is set correctly."""
    client = AgentOSClient(base_url="http://localhost:7777", api_key="custom-key")
    assert client.api_key == "custom-key"


def test_init_api_key_from_env():
    """Verify API key falls back to environment variable."""
    with patch.dict(os.environ, {"AGNO_API_KEY": "env-api-key"}):
        client = AgentOSClient(base_url="http://localhost:7777")
        assert client.api_key == "env-api-key"


@pytest.mark.asyncio
async def test_context_manager_creates_client():
    """Verify context manager creates HTTP client."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        assert client._http_client is not None


@pytest.mark.asyncio
async def test_context_manager_closes_client():
    """Verify context manager closes HTTP client on exit."""
    client = AgentOSClient(base_url="http://localhost:7777")
    async with client:
        http_client = client._http_client
        assert http_client is not None
    assert client._http_client is None


@pytest.mark.asyncio
async def test_connect_method():
    """Verify connect method creates HTTP client."""
    client = AgentOSClient(base_url="http://localhost:7777")
    assert client._http_client is None

    result = await client.connect()
    assert result is client  # Returns self for chaining
    assert client._http_client is not None

    await client.close()


@pytest.mark.asyncio
async def test_close_method():
    """Verify close method cleans up HTTP client."""
    client = AgentOSClient(base_url="http://localhost:7777")
    await client.connect()
    assert client._http_client is not None

    await client.close()
    assert client._http_client is None


@pytest.mark.asyncio
async def test_close_when_not_connected():
    """Verify close is safe when client is not connected."""
    client = AgentOSClient(base_url="http://localhost:7777")
    await client.close()  # Should not raise


def test_sync_context_manager():
    """Verify sync context manager functionality."""
    with AgentOSClient(base_url="http://localhost:7777") as client:
        assert client.base_url == "http://localhost:7777"
        # We can't easily verify cleanup here because it's async and happens in __exit__
        # But we can verify that entering the context works and returns the client
        assert isinstance(client, AgentOSClient)


def test_headers_with_api_key():
    """Verify Authorization header is set when API key is provided."""
    client = AgentOSClient(base_url="http://localhost:7777", api_key="my-key")
    headers = client._get_headers()
    assert headers["Authorization"] == "Bearer my-key"


def test_headers_without_api_key():
    """Verify no Authorization header when API key is not provided."""
    client = AgentOSClient(base_url="http://localhost:7777", api_key=None)
    # Override the default from env
    client.api_key = None
    headers = client._get_headers()
    assert "Authorization" not in headers


@pytest.mark.asyncio
async def test_get_method():
    """Verify _get method makes correct HTTP request."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": "test"}
        mock_response.raise_for_status = MagicMock()
        mock_response.content = b'{"data": "test"}'

        with patch.object(client._http_client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            result = await client._get("/test-endpoint")

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "GET"
            assert "http://localhost:7777/test-endpoint" in str(call_args)
            assert result == {"data": "test"}


@pytest.mark.asyncio
async def test_post_method():
    """Verify _post method makes correct HTTP request."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        mock_response = MagicMock()
        mock_response.json.return_value = {"created": True}
        mock_response.raise_for_status = MagicMock()
        mock_response.content = b'{"created": true}'

        with patch.object(client._http_client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            result = await client._post("/test-endpoint", {"key": "value"})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "POST"
            assert result == {"created": True}


@pytest.mark.asyncio
async def test_patch_method():
    """Verify _patch method makes correct HTTP request."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        mock_response = MagicMock()
        mock_response.json.return_value = {"updated": True}
        mock_response.raise_for_status = MagicMock()
        mock_response.content = b'{"updated": true}'

        with patch.object(client._http_client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            result = await client._patch("/test-endpoint", {"key": "value"})

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "PATCH"
            assert result == {"updated": True}


@pytest.mark.asyncio
async def test_delete_method():
    """Verify _delete method makes correct HTTP request."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.content = b''

        with patch.object(client._http_client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            await client._delete("/test-endpoint")

            mock_request.assert_called_once()
            call_args = mock_request.call_args
            assert call_args[0][0] == "DELETE"


@pytest.mark.asyncio
async def test_get_config():
    """Verify get_config returns ConfigResponse."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        mock_data = {
            "os_id": "test-os",
            "name": "Test OS",
            "description": "Test description",
            "databases": ["db-1"],
            "agents": [],
            "teams": [],
            "workflows": [],
            "interfaces": [],
        }
        with patch.object(client, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_data
            config = await client.get_config()

            mock_get.assert_called_once_with("/config")
            assert config.os_id == "test-os"
            assert config.name == "Test OS"


@pytest.mark.asyncio
async def test_get_agent():
    """Verify get_agent returns AgentResponse."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        mock_data = {
            "id": "agent-1",
            "name": "Test Agent",
            "model": {"name": "GPT-4o", "model": "gpt-4o", "provider": "openai"},
            "tools": {"calculator": {"name": "calculator"}},
        }
        with patch.object(client, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_data
            agent = await client.get_agent("agent-1")

            mock_get.assert_called_once_with("/agents/agent-1")
            assert agent.id == "agent-1"
            assert agent.name == "Test Agent"


@pytest.mark.asyncio
async def test_get_team():
    """Verify get_team returns TeamResponse."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        mock_data = {
            "id": "team-1",
            "name": "Test Team",
            "model": {"name": "GPT-4o", "model": "gpt-4o", "provider": "openai"},
            "members": [],
        }
        with patch.object(client, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_data
            team = await client.get_team("team-1")

            mock_get.assert_called_once_with("/teams/team-1")
            assert team.id == "team-1"
            assert team.name == "Test Team"


@pytest.mark.asyncio
async def test_get_workflow():
    """Verify get_workflow returns WorkflowResponse."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        mock_data = {
            "id": "workflow-1",
            "name": "Test Workflow",
        }
        with patch.object(client, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_data
            workflow = await client.get_workflow("workflow-1")

            mock_get.assert_called_once_with("/workflows/workflow-1")
            assert workflow.id == "workflow-1"
            assert workflow.name == "Test Workflow"


@pytest.mark.asyncio
async def test_create_memory():
    """Verify create_memory creates a new memory."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        mock_data = {
            "memory_id": "mem-123",
            "memory": "User likes blue",
            "user_id": "user-1",
            "topics": ["preferences"],
        }
        with patch.object(client, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_data
            memory = await client.create_memory(
                memory="User likes blue",
                user_id="user-1",
                topics=["preferences"],
            )

            mock_post.assert_called_once()
            assert memory.memory_id == "mem-123"
            assert memory.memory == "User likes blue"


@pytest.mark.asyncio
async def test_get_memory():
    """Verify get_memory retrieves a memory."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        mock_data = {
            "memory_id": "mem-123",
            "memory": "User likes blue",
            "user_id": "user-1",
            "topics": ["preferences"],
        }
        with patch.object(client, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_data
            memory = await client.get_memory("mem-123")

            assert "mem-123" in str(mock_get.call_args)
            assert memory.memory_id == "mem-123"


@pytest.mark.asyncio
async def test_list_memories():
    """Verify list_memories returns paginated memories."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        mock_data = {
            "data": [
                {
                    "memory_id": "mem-1",
                    "memory": "Memory 1",
                    "user_id": "user-1",
                    "topics": [],
                }
            ],
            "meta": {"page": 1, "limit": 20, "total": 1, "total_pages": 1},
        }
        with patch.object(client, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_data
            result = await client.list_memories(user_id="user-1")

            assert len(result.data) == 1
            assert result.data[0].memory_id == "mem-1"


@pytest.mark.asyncio
async def test_update_memory():
    """Verify update_memory updates a memory."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        mock_data = {
            "memory_id": "mem-123",
            "memory": "Updated memory",
            "user_id": "user-1",
            "topics": ["updated"],
        }
        with patch.object(client, "_patch", new_callable=AsyncMock) as mock_patch:
            mock_patch.return_value = mock_data
            memory = await client.update_memory(
                memory_id="mem-123",
                memory="Updated memory",
                user_id="user-1",
            )

            mock_patch.assert_called_once()
            assert memory.memory == "Updated memory"


@pytest.mark.asyncio
async def test_delete_memory():
    """Verify delete_memory deletes a memory."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        with patch.object(client, "_delete", new_callable=AsyncMock) as mock_delete:
            await client.delete_memory("mem-123", user_id="user-1")
            mock_delete.assert_called_once()


@pytest.mark.asyncio
async def test_list_sessions():
    """Verify list_sessions returns paginated sessions."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        mock_data = {
            "data": [
                {
                    "session_id": "sess-1",
                    "session_name": "Test Session",
                }
            ],
            "meta": {"page": 1, "limit": 20, "total": 1, "total_pages": 1},
        }
        with patch.object(client, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_data
            result = await client.list_sessions()

            assert len(result.data) == 1
            assert result.data[0].session_id == "sess-1"


@pytest.mark.asyncio
async def test_create_session():
    """Verify create_session creates a new session."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        mock_data = {
            "agent_session_id": "agent-sess-123",
            "session_id": "sess-123",
            "session_name": "New Session",
            "agent_id": "agent-1",
            "user_id": "user-1",
        }
        with patch.object(client, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_data
            session = await client.create_session(agent_id="agent-1", user_id="user-1")

            mock_post.assert_called_once()
            assert session.session_id == "sess-123"


@pytest.mark.asyncio
async def test_get_session():
    """Verify get_session retrieves a session."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        mock_data = {
            "agent_session_id": "agent-sess-123",
            "session_id": "sess-123",
            "session_name": "Test Session",
            "agent_id": "agent-1",
            "user_id": "user-1",
        }
        with patch.object(client, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_data
            session = await client.get_session("sess-123")

            assert "sess-123" in str(mock_get.call_args)
            assert session.session_id == "sess-123"


@pytest.mark.asyncio
async def test_delete_session():
    """Verify delete_session deletes a session."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        with patch.object(client, "_delete", new_callable=AsyncMock) as mock_delete:
            await client.delete_session("sess-123")
            mock_delete.assert_called_once()


@pytest.mark.asyncio
async def test_list_eval_runs():
    """Verify list_eval_runs returns paginated evals."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        mock_data = {
            "data": [
                {
                    "id": "eval-1",
                    "name": "Test Eval",
                    "eval_type": "accuracy",
                    "eval_data": {"score": 0.95},
                }
            ],
            "meta": {"page": 1, "limit": 20, "total": 1, "total_pages": 1},
        }
        with patch.object(client, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_data
            result = await client.list_eval_runs()

            assert len(result.data) == 1
            assert result.data[0].id == "eval-1"


@pytest.mark.asyncio
async def test_get_eval_run():
    """Verify get_eval_run retrieves an eval."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        mock_data = {
            "id": "eval-123",
            "name": "Test Eval",
            "eval_type": "accuracy",
            "eval_data": {"score": 0.95},
        }
        with patch.object(client, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_data
            eval_run = await client.get_eval_run("eval-123")

            assert "eval-123" in str(mock_get.call_args)
            assert eval_run.id == "eval-123"


@pytest.mark.asyncio
async def test_list_content():
    """Verify list_content returns paginated content."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        mock_data = {
            "data": [
                {
                    "id": "content-1",
                    "name": "Test Document",
                }
            ],
            "meta": {"page": 1, "limit": 20, "total": 1, "total_pages": 1},
        }
        with patch.object(client, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_data
            result = await client.list_content()

            assert len(result.data) == 1
            assert result.data[0].id == "content-1"


@pytest.mark.asyncio
async def test_get_content():
    """Verify get_content retrieves content."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        mock_data = {
            "id": "content-123",
            "name": "Test Document",
        }
        with patch.object(client, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_data
            content = await client.get_content("content-123")

            assert "content-123" in str(mock_get.call_args)
            assert content.id == "content-123"


@pytest.mark.asyncio
async def test_search_knowledge():
    """Verify search_knowledge searches the knowledge base."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        mock_data = {
            "data": [
                {
                    "id": "result-1",
                    "content": "Matching content",
                }
            ],
            "meta": {"page": 1, "limit": 20, "total": 1, "total_pages": 1},
        }
        with patch.object(client, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_data
            result = await client.search_knowledge(query="test query")

            mock_post.assert_called_once()
            assert len(result.data) == 1


@pytest.mark.asyncio
async def test_get_knowledge_config():
    """Verify get_knowledge_config returns config."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        mock_data = {}
        with patch.object(client, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_data
            await client.get_knowledge_config()

            assert "/knowledge/config" in str(mock_get.call_args)


@pytest.mark.asyncio
async def test_run_agent():
    """Verify run_agent executes an agent run."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        mock_data = {
            "run_id": "run-123",
            "agent_id": "agent-1",
            "content": "Hello! How can I help?",
            "created_at": 1234567890,
        }
        with patch.object(client, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_data
            result = await client.run_agent(
                agent_id="agent-1",
                message="Hello",
            )

            mock_post.assert_called_once()
            assert result.run_id == "run-123"
            assert result.content == "Hello! How can I help?"


@pytest.mark.asyncio
async def test_run_team():
    """Verify run_team executes a team run."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        mock_data = {
            "run_id": "run-123",
            "team_id": "team-1",
            "content": "Team response",
            "created_at": 1234567890,
        }
        with patch.object(client, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_data
            result = await client.run_team(
                team_id="team-1",
                message="Hello team",
            )

            mock_post.assert_called_once()
            assert result.run_id == "run-123"


@pytest.mark.asyncio
async def test_run_workflow():
    """Verify run_workflow executes a workflow run."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        mock_data = {
            "run_id": "run-123",
            "workflow_id": "workflow-1",
            "content": "Workflow output",
            "created_at": 1234567890,
        }
        with patch.object(client, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_data
            result = await client.run_workflow(
                workflow_id="workflow-1",
                message="Start workflow",
            )

            mock_post.assert_called_once()
            assert result.run_id == "run-123"


@pytest.mark.asyncio
async def test_cancel_agent_run():
    """Verify cancel_agent_run cancels a run."""
    async with AgentOSClient(base_url="http://localhost:7777") as client:
        with patch.object(client, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = None
            await client.cancel_agent_run("agent-1", "run-123")

            mock_post.assert_called_once()
            assert "/agents/agent-1/runs/run-123/cancel" in str(mock_post.call_args)


@pytest.mark.asyncio
async def test_get_creates_client_lazily():
    """Verify _get creates HTTP client if not exists."""
    client = AgentOSClient(base_url="http://localhost:7777")
    assert client._http_client is None

    mock_response = MagicMock()
    mock_response.json.return_value = {"data": "test"}
    mock_response.raise_for_status = MagicMock()
    mock_response.content = b'{"data": "test"}'

    with patch("agno.os.client.AsyncClient") as MockAsyncClient:
        mock_http_client = AsyncMock()
        mock_http_client.request.return_value = mock_response
        MockAsyncClient.return_value = mock_http_client

        await client._get("/test")

        MockAsyncClient.assert_called_once()
        assert client._http_client is mock_http_client

    await client.close()


@pytest.mark.asyncio
async def test_post_creates_client_lazily():
    """Verify _post creates HTTP client if not exists."""
    client = AgentOSClient(base_url="http://localhost:7777")
    assert client._http_client is None

    mock_response = MagicMock()
    mock_response.json.return_value = {"data": "test"}
    mock_response.raise_for_status = MagicMock()
    mock_response.content = b'{"data": "test"}'

    with patch("agno.os.client.AsyncClient") as MockAsyncClient:
        mock_http_client = AsyncMock()
        mock_http_client.request.return_value = mock_response
        MockAsyncClient.return_value = mock_http_client

        await client._post("/test", {})

        MockAsyncClient.assert_called_once()

    await client.close()


# Streaming Methods Tests


@pytest.mark.asyncio
async def test_stream_agent_run_returns_typed_events():
    """Verify stream_agent_run yields typed RunOutputEvent objects."""
    from agno.run.agent import RunStartedEvent, RunContentEvent, RunCompletedEvent

    client = AgentOSClient(base_url="http://localhost:7777")

    # Mock SSE lines
    mock_lines = [
        'data: {"event": "RunStarted", "run_id": "run-123", "agent_id": "agent-1", "created_at": 1234567890}',
        'data: {"event": "RunContent", "content": "Hello", "content_type": "str", "run_id": "run-123", "agent_id": "agent-1", "created_at": 1234567890}',
        'data: {"event": "RunCompleted", "run_id": "run-123", "agent_id": "agent-1", "created_at": 1234567890}',
    ]

    async def async_generator():
        for line in mock_lines:
            yield line

    with patch.object(client, "_stream_post_form_data") as mock_stream:
        mock_stream.return_value = async_generator()

        events = []
        async for event in client.stream_agent_run("agent-123", "test message"):
            events.append(event)

        assert len(events) == 3
        assert isinstance(events[0], RunStartedEvent)
        assert isinstance(events[1], RunContentEvent)
        assert events[1].content == "Hello"
        assert isinstance(events[2], RunCompletedEvent)

    await client.close()


@pytest.mark.asyncio
async def test_stream_handles_invalid_json():
    """Verify invalid JSON is logged and skipped."""
    from agno.run.agent import RunStartedEvent, RunCompletedEvent

    client = AgentOSClient(base_url="http://localhost:7777")

    mock_lines = [
        'data: {"event": "RunStarted", "run_id": "run-123", "agent_id": "agent-1", "created_at": 1234567890}',
        'data: {invalid json}',  # Bad JSON
        'data: {"event": "RunCompleted", "run_id": "run-123", "agent_id": "agent-1", "created_at": 1234567890}',
    ]

    async def async_generator():
        for line in mock_lines:
            yield line

    with patch.object(client, "_stream_post_form_data") as mock_stream:
        mock_stream.return_value = async_generator()

        events = []
        with patch("agno.utils.log.logger") as mock_logger:
            async for event in client.stream_agent_run("agent-123", "test"):
                events.append(event)

            # Should skip invalid event and continue
            assert len(events) == 2
            assert isinstance(events[0], RunStartedEvent)
            assert isinstance(events[1], RunCompletedEvent)
            assert mock_logger.error.called

    await client.close()


@pytest.mark.asyncio
async def test_stream_handles_unknown_event_type():
    """Verify unknown event types are logged and skipped."""
    from agno.run.agent import RunStartedEvent, RunCompletedEvent

    client = AgentOSClient(base_url="http://localhost:7777")

    mock_lines = [
        'data: {"event": "RunStarted", "run_id": "run-123", "agent_id": "agent-1", "created_at": 1234567890}',
        'data: {"event": "FutureEventType", "data": "something"}',  # Unknown type
        'data: {"event": "RunCompleted", "run_id": "run-123", "agent_id": "agent-1", "created_at": 1234567890}',
    ]

    async def async_generator():
        for line in mock_lines:
            yield line

    with patch.object(client, "_stream_post_form_data") as mock_stream:
        mock_stream.return_value = async_generator()

        events = []
        with patch("agno.utils.log.logger") as mock_logger:
            async for event in client.stream_agent_run("agent-123", "test"):
                events.append(event)

            # Should skip unknown event and continue
            assert len(events) == 2
            assert isinstance(events[0], RunStartedEvent)
            assert isinstance(events[1], RunCompletedEvent)
            assert mock_logger.error.called

    await client.close()


@pytest.mark.asyncio
async def test_stream_handles_empty_lines():
    """Verify empty lines and comments are skipped."""
    from agno.run.agent import RunStartedEvent, RunCompletedEvent

    client = AgentOSClient(base_url="http://localhost:7777")

    mock_lines = [
        "",  # Empty line
        ": comment",  # SSE comment
        'data: {"event": "RunStarted", "run_id": "run-123", "agent_id": "agent-1", "created_at": 1234567890}',
        "",  # Another empty line
        'data: {"event": "RunCompleted", "run_id": "run-123", "agent_id": "agent-1", "created_at": 1234567890}',
    ]

    async def async_generator():
        for line in mock_lines:
            yield line

    with patch.object(client, "_stream_post_form_data") as mock_stream:
        mock_stream.return_value = async_generator()

        events = []
        async for event in client.stream_agent_run("agent-123", "test"):
            events.append(event)

        # Should only yield actual events
        assert len(events) == 2
        assert isinstance(events[0], RunStartedEvent)
        assert isinstance(events[1], RunCompletedEvent)

    await client.close()


@pytest.mark.asyncio
async def test_stream_team_run_returns_typed_events():
    """Verify stream_team_run yields BaseTeamRunEvent objects."""
    from agno.run.agent import RunStartedEvent, RunCompletedEvent

    client = AgentOSClient(base_url="http://localhost:7777")

    # Team runs can emit agent events
    mock_lines = [
        'data: {"event": "RunStarted", "run_id": "run-123", "agent_id": "agent-1", "created_at": 1234567890}',
        'data: {"event": "RunCompleted", "run_id": "run-123", "agent_id": "agent-1", "created_at": 1234567890}',
    ]

    async def async_generator():
        for line in mock_lines:
            yield line

    with patch.object(client, "_stream_post_form_data") as mock_stream:
        mock_stream.return_value = async_generator()

        events = []
        async for event in client.stream_team_run("team-123", "test message"):
            events.append(event)

        assert len(events) == 2
        assert isinstance(events[0], RunStartedEvent)
        assert isinstance(events[1], RunCompletedEvent)

    await client.close()


@pytest.mark.asyncio
async def test_stream_workflow_run_returns_typed_events():
    """Verify stream_workflow_run yields WorkflowRunOutputEvent objects."""
    from agno.run.agent import RunStartedEvent, RunCompletedEvent

    client = AgentOSClient(base_url="http://localhost:7777")

    # Workflow runs can emit agent events
    mock_lines = [
        'data: {"event": "RunStarted", "run_id": "run-123", "agent_id": "agent-1", "created_at": 1234567890}',
        'data: {"event": "RunCompleted", "run_id": "run-123", "agent_id": "agent-1", "created_at": 1234567890}',
    ]

    async def async_generator():
        for line in mock_lines:
            yield line

    with patch.object(client, "_stream_post_form_data") as mock_stream:
        mock_stream.return_value = async_generator()

        events = []
        async for event in client.stream_workflow_run("workflow-123", "test message"):
            events.append(event)

        assert len(events) == 2
        assert isinstance(events[0], RunStartedEvent)
        assert isinstance(events[1], RunCompletedEvent)

    await client.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
