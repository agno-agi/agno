"""Unit tests for A2AClient."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.a2a import (
    A2AAgentNotFoundError,
    A2AClient,
    A2ARequestError,
    A2ATaskFailedError,
    StreamEvent,
    TaskResult,
)


class TestA2AClientInit:
    """Test A2AClient initialization."""

    def test_init_default_values(self):
        """Test client initialization with default values."""
        client = A2AClient("http://localhost:7777")
        assert client.base_url == "http://localhost:7777"
        assert client.timeout == 300.0
        assert client.a2a_prefix == "/a2a"
        assert client._http_client is None

    def test_init_custom_values(self):
        """Test client initialization with custom values."""
        client = A2AClient(
            "http://localhost:8080/",
            timeout=60.0,
            a2a_prefix="/api/a2a",
        )
        assert client.base_url == "http://localhost:8080"  # Trailing slash stripped
        assert client.timeout == 60.0
        assert client.a2a_prefix == "/api/a2a"

    def test_get_endpoint(self):
        """Test endpoint URL building."""
        client = A2AClient("http://localhost:7777")
        assert client._get_endpoint("/message/send") == "http://localhost:7777/a2a/message/send"


class TestA2AClientContextManager:
    """Test A2AClient context manager."""

    @pytest.mark.asyncio
    async def test_async_context_manager(self):
        """Test async context manager creates and closes client."""
        with patch("agno.a2a.client.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            async with A2AClient("http://localhost:7777") as client:
                assert client._http_client is not None

            mock_client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_method(self):
        """Test explicit connect method."""
        with patch("agno.a2a.client.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            client = A2AClient("http://localhost:7777")
            assert client._http_client is None

            result = await client.connect()
            assert result is client
            assert client._http_client is not None

            await client.close()
            mock_client.aclose.assert_called_once()


class TestBuildMessageRequest:
    """Test message request building."""

    def test_basic_request(self):
        """Test building basic message request."""
        client = A2AClient("http://localhost:7777")
        request = client._build_message_request(
            agent_id="my-agent",
            message="Hello",
            stream=False,
        )

        assert request["jsonrpc"] == "2.0"
        assert request["method"] == "message/send"
        assert "id" in request
        assert request["params"]["message"]["agentId"] == "my-agent"
        assert request["params"]["message"]["role"] == "user"
        assert request["params"]["message"]["parts"][0]["kind"] == "text"
        assert request["params"]["message"]["parts"][0]["text"] == "Hello"

    def test_streaming_request(self):
        """Test building streaming message request."""
        client = A2AClient("http://localhost:7777")
        request = client._build_message_request(
            agent_id="my-agent",
            message="Hello",
            stream=True,
        )

        assert request["method"] == "message/stream"

    def test_request_with_context(self):
        """Test building request with context ID."""
        client = A2AClient("http://localhost:7777")
        request = client._build_message_request(
            agent_id="my-agent",
            message="Hello",
            context_id="session-123",
            user_id="user-456",
            stream=False,
        )

        assert request["params"]["message"]["contextId"] == "session-123"
        assert request["params"]["message"]["metadata"]["userId"] == "user-456"


class TestParseTaskResult:
    """Test task result parsing."""

    def test_parse_basic_response(self):
        """Test parsing basic A2A response."""
        client = A2AClient("http://localhost:7777")
        response_data = {
            "jsonrpc": "2.0",
            "id": "req-1",
            "result": {
                "id": "task-123",
                "context_id": "ctx-456",
                "status": {"state": "completed"},
                "history": [
                    {
                        "role": "agent",
                        "parts": [{"kind": "text", "text": "Hello, world!"}],
                    }
                ],
            },
        }

        result = client._parse_task_result(response_data)

        assert isinstance(result, TaskResult)
        assert result.task_id == "task-123"
        assert result.context_id == "ctx-456"
        assert result.status == "completed"
        assert result.content == "Hello, world!"
        assert result.is_completed
        assert not result.is_failed

    def test_parse_failed_response(self):
        """Test parsing failed task response."""
        client = A2AClient("http://localhost:7777")
        response_data = {
            "result": {
                "id": "task-123",
                "context_id": "ctx-456",
                "status": {"state": "failed"},
                "history": [
                    {
                        "role": "agent",
                        "parts": [{"kind": "text", "text": "Error occurred"}],
                    }
                ],
            },
        }

        result = client._parse_task_result(response_data)

        assert result.status == "failed"
        assert result.is_failed
        assert result.content == "Error occurred"

    def test_parse_with_artifacts(self):
        """Test parsing response with artifacts."""
        client = A2AClient("http://localhost:7777")
        response_data = {
            "result": {
                "id": "task-123",
                "context_id": "ctx-456",
                "status": {"state": "completed"},
                "history": [],
                "artifacts": [
                    {
                        "artifact_id": "art-1",
                        "name": "image.png",
                        "mimeType": "image/png",
                        "uri": "http://example.com/image.png",
                    }
                ],
            },
        }

        result = client._parse_task_result(response_data)

        assert len(result.artifacts) == 1
        assert result.artifacts[0].artifact_id == "art-1"
        assert result.artifacts[0].name == "image.png"


class TestParseStreamEvent:
    """Test stream event parsing."""

    def test_parse_content_event(self):
        """Test parsing content event."""
        client = A2AClient("http://localhost:7777")
        # Content events have kind="message" and parts with text
        data = {
            "result": {
                "kind": "message",
                "messageId": "msg-1",
                "role": "agent",
                "parts": [{"kind": "text", "text": "Hello"}],
                "contextId": "ctx-456",
                "taskId": "task-123",
            },
        }

        event = client._parse_stream_event(data)

        assert isinstance(event, StreamEvent)
        assert event.event_type == "content"
        assert event.content == "Hello"
        assert event.is_content
        assert not event.is_final

    def test_parse_status_event(self):
        """Test parsing status event."""
        client = A2AClient("http://localhost:7777")
        data = {
            "result": {
                "kind": "status-update",
                "taskId": "task-123",
                "contextId": "ctx-456",
                "status": {"state": "working"},
                "final": False,
            },
        }

        event = client._parse_stream_event(data)

        assert event.event_type == "working"
        assert not event.is_final

    def test_parse_completed_event(self):
        """Test parsing completed event."""
        client = A2AClient("http://localhost:7777")
        data = {
            "result": {
                "kind": "status-update",
                "taskId": "task-123",
                "contextId": "ctx-456",
                "status": {"state": "completed"},
                "final": True,
            },
        }

        event = client._parse_stream_event(data)

        assert event.event_type == "completed"
        assert event.is_final


class TestSendMessage:
    """Test send_message method."""

    @pytest.mark.asyncio
    async def test_send_message_success(self):
        """Test successful message send."""
        with patch("agno.a2a.client.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "jsonrpc": "2.0",
                "id": "req-1",
                "result": {
                    "id": "task-123",
                    "context_id": "ctx-456",
                    "status": {"state": "completed"},
                    "history": [
                        {
                            "role": "agent",
                            "parts": [{"kind": "text", "text": "The answer is 4"}],
                        }
                    ],
                },
            }
            mock_response.raise_for_status = MagicMock()

            mock_http_client = AsyncMock()
            mock_http_client.post.return_value = mock_response
            mock_client_class.return_value = mock_http_client

            async with A2AClient("http://localhost:7777") as client:
                result = await client.send_message(
                    agent_id="my-agent",
                    message="What is 2 + 2?",
                )

            assert result.content == "The answer is 4"
            assert result.is_completed
            mock_http_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_message_agent_not_found(self):
        """Test send_message with non-existent agent."""
        with patch("agno.a2a.client.AsyncClient") as mock_client_class:
            from httpx import HTTPStatusError, Request, Response

            mock_response = Response(404, request=Request("POST", "http://test"))
            mock_http_client = AsyncMock()
            mock_http_client.post.side_effect = HTTPStatusError(
                "Not Found", request=mock_response.request, response=mock_response
            )
            mock_client_class.return_value = mock_http_client

            async with A2AClient("http://localhost:7777") as client:
                with pytest.raises(A2AAgentNotFoundError) as exc_info:
                    await client.send_message(
                        agent_id="nonexistent-agent",
                        message="Hello",
                    )
                assert "nonexistent-agent" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_send_message_task_failed(self):
        """Test send_message with failed task."""
        with patch("agno.a2a.client.AsyncClient") as mock_client_class:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "result": {
                    "id": "task-123",
                    "context_id": "ctx-456",
                    "status": {"state": "failed"},
                    "history": [
                        {
                            "role": "agent",
                            "parts": [{"kind": "text", "text": "Error: Something went wrong"}],
                        }
                    ],
                },
            }
            mock_response.raise_for_status = MagicMock()

            mock_http_client = AsyncMock()
            mock_http_client.post.return_value = mock_response
            mock_client_class.return_value = mock_http_client

            async with A2AClient("http://localhost:7777") as client:
                with pytest.raises(A2ATaskFailedError) as exc_info:
                    await client.send_message(
                        agent_id="my-agent",
                        message="Do something",
                    )
                assert "task-123" in str(exc_info.value)


class TestStreamMessage:
    """Test stream_message method."""

    @pytest.mark.asyncio
    async def test_stream_message_success(self):
        """Test successful message streaming."""
        with patch("agno.a2a.client.AsyncClient") as mock_client_class:
            # Create mock streaming response
            async def mock_aiter_lines():
                lines = [
                    '{"result": {"task_id": "task-123", "status": {"state": "working"}}}',
                    '{"result": {"messageId": "m1", "parts": [{"text": "Hello"}]}}',
                    '{"result": {"messageId": "m2", "parts": [{"text": " World"}]}}',
                    '{"result": {"task_id": "task-123", "status": {"state": "completed"}, "final": true}}',
                ]
                for line in lines:
                    yield line

            mock_stream_response = MagicMock()
            mock_stream_response.status_code = 200
            mock_stream_response.raise_for_status = MagicMock()
            mock_stream_response.aiter_lines = mock_aiter_lines

            # Create async context manager mock
            mock_stream_cm = AsyncMock()
            mock_stream_cm.__aenter__.return_value = mock_stream_response
            mock_stream_cm.__aexit__.return_value = None

            mock_http_client = MagicMock()
            mock_http_client.stream.return_value = mock_stream_cm
            mock_http_client.aclose = AsyncMock()
            mock_client_class.return_value = mock_http_client

            events = []
            async with A2AClient("http://localhost:7777") as client:
                async for event in client.stream_message(
                    agent_id="my-agent",
                    message="Hello",
                ):
                    events.append(event)

            assert len(events) == 4
            # Check content events
            content_events = [e for e in events if e.is_content]
            assert len(content_events) == 2
            assert content_events[0].content == "Hello"
            assert content_events[1].content == " World"


class TestSchemas:
    """Test schema dataclasses."""

    def test_task_result_properties(self):
        """Test TaskResult helper properties."""
        result = TaskResult(
            task_id="t1",
            context_id="c1",
            status="completed",
            content="Done",
        )
        assert result.is_completed
        assert not result.is_failed
        assert not result.is_canceled

        failed = TaskResult(
            task_id="t2",
            context_id="c2",
            status="failed",
            content="Error",
        )
        assert not failed.is_completed
        assert failed.is_failed

    def test_stream_event_properties(self):
        """Test StreamEvent helper properties."""
        content_event = StreamEvent(
            event_type="content",
            content="Hello",
        )
        assert content_event.is_content
        assert not content_event.is_final

        completed_event = StreamEvent(
            event_type="completed",
            is_final=True,
        )
        assert completed_event.is_completed
        assert completed_event.is_final


class TestExceptions:
    """Test exception classes."""

    def test_a2a_agent_not_found_error(self):
        """Test A2AAgentNotFoundError."""
        error = A2AAgentNotFoundError("my-agent")
        assert error.agent_id == "my-agent"
        assert "my-agent" in str(error)

    def test_a2a_task_failed_error(self):
        """Test A2ATaskFailedError."""
        error = A2ATaskFailedError("task-123", "Something went wrong")
        assert error.task_id == "task-123"
        assert error.reason == "Something went wrong"
        assert "task-123" in str(error)

    def test_a2a_request_error(self):
        """Test A2ARequestError."""
        error = A2ARequestError(400, "Bad request")
        assert error.status_code == 400
        assert error.detail == "Bad request"

