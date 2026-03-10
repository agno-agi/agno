"""
Unit tests for AgentOSClient.

Tests cover:
1. Client initialization and configuration
2. HTTP method helpers
3. Discovery operations
4. Memory operations
5. Session operations
6. Eval operations
7. Knowledge operations
8. Run operations
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.client import AgentOSClient


def test_init_with_base_url():
    """Verify basic initialization with base URL."""
    client = AgentOSClient(base_url="http://localhost:7777")
    assert client.base_url == "http://localhost:7777"
    assert client.timeout == 60


def test_init_strips_trailing_slash():
    """Verify trailing slash is removed from base URL."""
    client = AgentOSClient(base_url="http://localhost:7777/")
    assert client.base_url == "http://localhost:7777"


def test_init_with_custom_timeout():
    """Verify custom timeout is respected."""
    client = AgentOSClient(base_url="http://localhost:7777", timeout=120)
    assert client.timeout == 120


@pytest.mark.asyncio
async def test_get_method():
    """Verify _aget method makes correct HTTP request."""
    client = AgentOSClient(base_url="http://localhost:7777")

    mock_response = MagicMock()
    mock_response.json.return_value = {"data": "test"}
    mock_response.raise_for_status = MagicMock()
    mock_response.content = b'{"data": "test"}'

    mock_http_client = MagicMock()
    mock_http_client.request = AsyncMock(return_value=mock_response)

    with patch("agno.client.os.get_default_async_client", return_value=mock_http_client):
        result = await client._aget("/test-endpoint")

        mock_http_client.request.assert_called_once()
        call_args = mock_http_client.request.call_args
        assert call_args[0][0] == "GET"
        assert "http://localhost:7777/test-endpoint" in str(call_args)
        assert result == {"data": "test"}


@pytest.mark.asyncio
async def test_post_method():
    """Verify _apost method makes correct HTTP request."""
    client = AgentOSClient(base_url="http://localhost:7777")

    mock_response = MagicMock()
    mock_response.json.return_value = {"created": True}
    mock_response.raise_for_status = MagicMock()
    mock_response.content = b'{"created": true}'

    mock_http_client = MagicMock()
    mock_http_client.request = AsyncMock(return_value=mock_response)

    with patch("agno.client.os.get_default_async_client", return_value=mock_http_client):
        result = await client._apost("/test-endpoint", {"key": "value"})

        mock_http_client.request.assert_called_once()
        call_args = mock_http_client.request.call_args
        assert call_args[0][0] == "POST"
        assert result == {"created": True}


@pytest.mark.asyncio
async def test_patch_method():
    """Verify _apatch method makes correct HTTP request."""
    client = AgentOSClient(base_url="http://localhost:7777")

    mock_response = MagicMock()
    mock_response.json.return_value = {"updated": True}
    mock_response.raise_for_status = MagicMock()
    mock_response.content = b'{"updated": true}'

    mock_http_client = MagicMock()
    mock_http_client.request = AsyncMock(return_value=mock_response)

    with patch("agno.client.os.get_default_async_client", return_value=mock_http_client):
        result = await client._apatch("/test-endpoint", {"key": "value"})

        mock_http_client.request.assert_called_once()
        call_args = mock_http_client.request.call_args
        assert call_args[0][0] == "PATCH"
        assert result == {"updated": True}


@pytest.mark.asyncio
async def test_delete_method():
    """Verify _adelete method makes correct HTTP request."""
    client = AgentOSClient(base_url="http://localhost:7777")

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.content = b""

    mock_http_client = MagicMock()
    mock_http_client.request = AsyncMock(return_value=mock_response)

    with patch("agno.client.os.get_default_async_client", return_value=mock_http_client):
        await client._adelete("/test-endpoint")

        mock_http_client.request.assert_called_once()
        call_args = mock_http_client.request.call_args
        assert call_args[0][0] == "DELETE"


@pytest.mark.asyncio
async def test_get_config():
    """Verify get_config returns ConfigResponse."""
    client = AgentOSClient(base_url="http://localhost:7777")
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
    with patch.object(client, "_aget", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_data
        config = await client.aget_config()

        mock_get.assert_called_once_with("/config", headers=None)
        assert config.os_id == "test-os"
        assert config.name == "Test OS"


@pytest.mark.asyncio
async def test_get_agent():
    """Verify get_agent returns AgentResponse."""
    client = AgentOSClient(base_url="http://localhost:7777")
    mock_data = {
        "id": "agent-1",
        "name": "Test Agent",
        "model": {"name": "GPT-4o", "model": "gpt-4o", "provider": "openai"},
        "tools": {"calculator": {"name": "calculator"}},
    }
    with patch.object(client, "_aget", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_data
        agent = await client.aget_agent("agent-1")

        mock_get.assert_called_once_with("/agents/agent-1", headers=None)
        assert agent.id == "agent-1"
        assert agent.name == "Test Agent"


@pytest.mark.asyncio
async def test_get_team():
    """Verify get_team returns TeamResponse."""
    client = AgentOSClient(base_url="http://localhost:7777")
    mock_data = {
        "id": "team-1",
        "name": "Test Team",
        "model": {"name": "GPT-4o", "model": "gpt-4o", "provider": "openai"},
        "members": [],
    }
    with patch.object(client, "_aget", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_data
        team = await client.aget_team("team-1")

        mock_get.assert_called_once_with("/teams/team-1", headers=None)
        assert team.id == "team-1"
        assert team.name == "Test Team"


@pytest.mark.asyncio
async def test_get_workflow():
    """Verify get_workflow returns WorkflowResponse."""
    client = AgentOSClient(base_url="http://localhost:7777")
    mock_data = {
        "id": "workflow-1",
        "name": "Test Workflow",
    }
    with patch.object(client, "_aget", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_data
        workflow = await client.aget_workflow("workflow-1")

        mock_get.assert_called_once_with("/workflows/workflow-1", headers=None)
        assert workflow.id == "workflow-1"
        assert workflow.name == "Test Workflow"


@pytest.mark.asyncio
async def test_create_memory():
    """Verify create_memory creates a new memory."""
    client = AgentOSClient(base_url="http://localhost:7777")
    mock_data = {
        "memory_id": "mem-123",
        "memory": "User likes blue",
        "user_id": "user-1",
        "topics": ["preferences"],
    }
    with patch.object(client, "_apost", new_callable=AsyncMock) as mock_post:
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
    client = AgentOSClient(base_url="http://localhost:7777")
    mock_data = {
        "memory_id": "mem-123",
        "memory": "User likes blue",
        "user_id": "user-1",
        "topics": ["preferences"],
    }
    with patch.object(client, "_aget", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_data
        memory = await client.get_memory("mem-123")

        assert "mem-123" in str(mock_get.call_args)
        assert memory.memory_id == "mem-123"


@pytest.mark.asyncio
async def test_list_memories():
    """Verify list_memories returns paginated memories."""
    client = AgentOSClient(base_url="http://localhost:7777")
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
    with patch.object(client, "_aget", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_data
        result = await client.list_memories(user_id="user-1")

        assert len(result.data) == 1
        assert result.data[0].memory_id == "mem-1"


@pytest.mark.asyncio
async def test_update_memory():
    """Verify update_memory updates a memory."""
    client = AgentOSClient(base_url="http://localhost:7777")
    mock_data = {
        "memory_id": "mem-123",
        "memory": "Updated memory",
        "user_id": "user-1",
        "topics": ["updated"],
    }
    with patch.object(client, "_apatch", new_callable=AsyncMock) as mock_patch:
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
    client = AgentOSClient(base_url="http://localhost:7777")
    with patch.object(client, "_adelete", new_callable=AsyncMock) as mock_delete:
        await client.delete_memory("mem-123", user_id="user-1")
        mock_delete.assert_called_once()


@pytest.mark.asyncio
async def test_list_sessions():
    """Verify list_sessions returns paginated sessions."""
    client = AgentOSClient(base_url="http://localhost:7777")
    mock_data = {
        "data": [
            {
                "session_id": "sess-1",
                "session_name": "Test Session",
            }
        ],
        "meta": {"page": 1, "limit": 20, "total": 1, "total_pages": 1},
    }
    with patch.object(client, "_aget", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_data
        result = await client.get_sessions()

        assert len(result.data) == 1
        assert result.data[0].session_id == "sess-1"


@pytest.mark.asyncio
async def test_create_session():
    """Verify create_session creates a new session."""
    client = AgentOSClient(base_url="http://localhost:7777")
    mock_data = {
        "agent_session_id": "agent-sess-123",
        "session_id": "sess-123",
        "session_name": "New Session",
        "agent_id": "agent-1",
        "user_id": "user-1",
    }
    with patch.object(client, "_apost", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_data
        session = await client.create_session(agent_id="agent-1", user_id="user-1")

        mock_post.assert_called_once()
        assert session.session_id == "sess-123"


@pytest.mark.asyncio
async def test_get_session():
    """Verify get_session retrieves a session."""
    client = AgentOSClient(base_url="http://localhost:7777")
    mock_data = {
        "agent_session_id": "agent-sess-123",
        "session_id": "sess-123",
        "session_name": "Test Session",
        "agent_id": "agent-1",
        "user_id": "user-1",
    }
    with patch.object(client, "_aget", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_data
        session = await client.get_session("sess-123")

        assert "sess-123" in str(mock_get.call_args)
        assert session.session_id == "sess-123"


@pytest.mark.asyncio
async def test_delete_session():
    """Verify delete_session deletes a session."""
    client = AgentOSClient(base_url="http://localhost:7777")
    with patch.object(client, "_adelete", new_callable=AsyncMock) as mock_delete:
        await client.delete_session("sess-123")
        mock_delete.assert_called_once()


@pytest.mark.asyncio
async def test_list_eval_runs():
    """Verify list_eval_runs returns paginated evals."""
    client = AgentOSClient(base_url="http://localhost:7777")
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
    with patch.object(client, "_aget", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_data
        result = await client.list_eval_runs()

        assert len(result.data) == 1
        assert result.data[0].id == "eval-1"


@pytest.mark.asyncio
async def test_get_eval_run():
    """Verify get_eval_run retrieves an eval."""
    client = AgentOSClient(base_url="http://localhost:7777")
    mock_data = {
        "id": "eval-123",
        "name": "Test Eval",
        "eval_type": "accuracy",
        "eval_data": {"score": 0.95},
    }
    with patch.object(client, "_aget", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_data
        eval_run = await client.get_eval_run("eval-123")

        assert "eval-123" in str(mock_get.call_args)
        assert eval_run.id == "eval-123"


@pytest.mark.asyncio
async def test_list_content():
    """Verify list_content returns paginated content."""
    client = AgentOSClient(base_url="http://localhost:7777")
    mock_data = {
        "data": [
            {
                "id": "content-1",
                "name": "Test Document",
            }
        ],
        "meta": {"page": 1, "limit": 20, "total": 1, "total_pages": 1},
    }
    with patch.object(client, "_aget", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_data
        result = await client.list_knowledge_content()

        assert len(result.data) == 1
        assert result.data[0].id == "content-1"


@pytest.mark.asyncio
async def test_get_content():
    """Verify get_content retrieves content."""
    client = AgentOSClient(base_url="http://localhost:7777")
    mock_data = {
        "id": "content-123",
        "name": "Test Document",
    }
    with patch.object(client, "_aget", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_data
        content = await client.get_knowledge_content("content-123")

        assert "content-123" in str(mock_get.call_args)
        assert content.id == "content-123"


@pytest.mark.asyncio
async def test_search_knowledge():
    """Verify search_knowledge searches the knowledge base."""
    client = AgentOSClient(base_url="http://localhost:7777")
    mock_data = {
        "data": [
            {
                "id": "result-1",
                "content": "Matching content",
            }
        ],
        "meta": {"page": 1, "limit": 20, "total": 1, "total_pages": 1},
    }
    with patch.object(client, "_apost", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_data
        result = await client.search_knowledge(query="test query")

        mock_post.assert_called_once()
        assert len(result.data) == 1


@pytest.mark.asyncio
async def test_get_knowledge_config():
    """Verify get_knowledge_config returns config."""
    client = AgentOSClient(base_url="http://localhost:7777")
    mock_data = {}
    with patch.object(client, "_aget", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_data
        await client.get_knowledge_config()

        assert "/knowledge/config" in str(mock_get.call_args)


@pytest.mark.asyncio
async def test_run_agent():
    """Verify run_agent executes an agent run."""
    client = AgentOSClient(base_url="http://localhost:7777")
    mock_data = {
        "run_id": "run-123",
        "agent_id": "agent-1",
        "content": "Hello! How can I help?",
        "created_at": 1234567890,
    }
    with patch.object(client, "_apost", new_callable=AsyncMock) as mock_post:
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
    client = AgentOSClient(base_url="http://localhost:7777")
    mock_data = {
        "run_id": "run-123",
        "team_id": "team-1",
        "content": "Team response",
        "created_at": 1234567890,
    }
    with patch.object(client, "_apost", new_callable=AsyncMock) as mock_post:
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
    client = AgentOSClient(base_url="http://localhost:7777")
    mock_data = {
        "run_id": "run-123",
        "workflow_id": "workflow-1",
        "content": "Workflow output",
        "created_at": 1234567890,
    }
    with patch.object(client, "_apost", new_callable=AsyncMock) as mock_post:
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
    client = AgentOSClient(base_url="http://localhost:7777")
    with patch.object(client, "_apost", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = None
        await client.cancel_agent_run("agent-1", "run-123")

        mock_post.assert_called_once()
        assert "/agents/agent-1/runs/run-123/cancel" in str(mock_post.call_args)


@pytest.mark.asyncio
async def test_headers_passed_through():
    """Verify headers are passed through to requests."""
    client = AgentOSClient(base_url="http://localhost:7777")
    mock_data = {
        "os_id": "test-os",
        "name": "Test OS",
        "databases": ["db-1"],
        "agents": [],
        "teams": [],
        "workflows": [],
        "interfaces": [],
    }

    with patch.object(client, "_aget", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_data
        headers = {"Authorization": "Bearer test-token", "X-Custom": "value"}
        await client.aget_config(headers=headers)

        mock_get.assert_called_once_with("/config", headers=headers)


# Streaming Methods Tests


@pytest.mark.asyncio
async def test_run_agent_stream_returns_typed_events():
    """Verify run_agent_stream yields typed RunOutputEvent objects."""
    from agno.run.agent import RunCompletedEvent, RunContentEvent, RunStartedEvent

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

    with patch.object(client, "_astream_post_form_data") as mock_stream:
        mock_stream.return_value = async_generator()

        events = []
        async for event in client.run_agent_stream("agent-123", "test message"):
            events.append(event)

        assert len(events) == 3
        assert isinstance(events[0], RunStartedEvent)
        assert isinstance(events[1], RunContentEvent)
        assert events[1].content == "Hello"
        assert isinstance(events[2], RunCompletedEvent)


@pytest.mark.asyncio
async def test_stream_handles_invalid_json():
    """Verify invalid JSON is logged and skipped."""
    from agno.run.agent import RunCompletedEvent, RunStartedEvent

    client = AgentOSClient(base_url="http://localhost:7777")

    mock_lines = [
        'data: {"event": "RunStarted", "run_id": "run-123", "agent_id": "agent-1", "created_at": 1234567890}',
        "data: {invalid json}",  # Bad JSON
        'data: {"event": "RunCompleted", "run_id": "run-123", "agent_id": "agent-1", "created_at": 1234567890}',
    ]

    async def async_generator():
        for line in mock_lines:
            yield line

    with patch.object(client, "_astream_post_form_data") as mock_stream:
        mock_stream.return_value = async_generator()

        events = []
        with patch("agno.utils.log.logger") as mock_logger:
            async for event in client.run_agent_stream("agent-123", "test"):
                events.append(event)

            # Should skip invalid event and continue
            assert len(events) == 2
            assert isinstance(events[0], RunStartedEvent)
            assert isinstance(events[1], RunCompletedEvent)
            assert mock_logger.error.called


@pytest.mark.asyncio
async def test_stream_handles_unknown_event_type():
    """Verify unknown event types are logged and skipped."""
    from agno.run.agent import RunCompletedEvent, RunStartedEvent

    client = AgentOSClient(base_url="http://localhost:7777")

    mock_lines = [
        'data: {"event": "RunStarted", "run_id": "run-123", "agent_id": "agent-1", "created_at": 1234567890}',
        'data: {"event": "FutureEventType", "data": "something"}',  # Unknown type
        'data: {"event": "RunCompleted", "run_id": "run-123", "agent_id": "agent-1", "created_at": 1234567890}',
    ]

    async def async_generator():
        for line in mock_lines:
            yield line

    with patch.object(client, "_astream_post_form_data") as mock_stream:
        mock_stream.return_value = async_generator()

        events = []
        with patch("agno.utils.log.logger") as mock_logger:
            async for event in client.run_agent_stream("agent-123", "test"):
                events.append(event)

            # Should skip unknown event and continue
            assert len(events) == 2
            assert isinstance(events[0], RunStartedEvent)
            assert isinstance(events[1], RunCompletedEvent)
            assert mock_logger.error.called


@pytest.mark.asyncio
async def test_stream_handles_empty_lines():
    """Verify empty lines and comments are skipped."""
    from agno.run.agent import RunCompletedEvent, RunStartedEvent

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

    with patch.object(client, "_astream_post_form_data") as mock_stream:
        mock_stream.return_value = async_generator()

        events = []
        async for event in client.run_agent_stream("agent-123", "test"):
            events.append(event)

        # Should only yield actual events
        assert len(events) == 2
        assert isinstance(events[0], RunStartedEvent)
        assert isinstance(events[1], RunCompletedEvent)


@pytest.mark.asyncio
async def test_run_team_stream_returns_typed_events():
    """Verify run_team_stream yields BaseTeamRunEvent objects."""
    from agno.run.agent import RunCompletedEvent, RunStartedEvent

    client = AgentOSClient(base_url="http://localhost:7777")

    # Team runs can emit agent events
    mock_lines = [
        'data: {"event": "RunStarted", "run_id": "run-123", "agent_id": "agent-1", "created_at": 1234567890}',
        'data: {"event": "RunCompleted", "run_id": "run-123", "agent_id": "agent-1", "created_at": 1234567890}',
    ]

    async def async_generator():
        for line in mock_lines:
            yield line

    with patch.object(client, "_astream_post_form_data") as mock_stream:
        mock_stream.return_value = async_generator()

        events = []
        async for event in client.run_team_stream("team-123", "test message"):
            events.append(event)

        assert len(events) == 2
        assert isinstance(events[0], RunStartedEvent)
        assert isinstance(events[1], RunCompletedEvent)


@pytest.mark.asyncio
async def test_run_workflow_stream_returns_typed_events():
    """Verify run_workflow_stream yields WorkflowRunOutputEvent objects."""
    from agno.run.agent import RunCompletedEvent, RunStartedEvent

    client = AgentOSClient(base_url="http://localhost:7777")

    # Workflow runs can emit agent events
    mock_lines = [
        'data: {"event": "RunStarted", "run_id": "run-123", "agent_id": "agent-1", "created_at": 1234567890}',
        'data: {"event": "RunCompleted", "run_id": "run-123", "agent_id": "agent-1", "created_at": 1234567890}',
    ]

    async def async_generator():
        for line in mock_lines:
            yield line

    with patch.object(client, "_astream_post_form_data") as mock_stream:
        mock_stream.return_value = async_generator()

        events = []
        async for event in client.run_workflow_stream("workflow-123", "test message"):
            events.append(event)

        assert len(events) == 2
        assert isinstance(events[0], RunStartedEvent)
        assert isinstance(events[1], RunCompletedEvent)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
