"""Unit tests for A2AClient."""

from typing import AsyncIterator, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from a2a.client import A2AClientError, A2AClientTimeoutError
from a2a.types import (
    AgentCapabilities,
    AgentInterface,
    Artifact,
    Message,
    Part,
    Role,
    StreamResponse,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)
from a2a.types import AgentCard as A2AAgentCard
from httpx import ConnectError, HTTPStatusError, Request, Response

from agno.client.a2a import (
    A2AClient,
    StreamEvent,
    TaskResult,
)
from agno.client.a2a.utils import map_stream_events_to_run_events
from agno.exceptions import RemoteServerUnavailableError
from agno.run.agent import (
    RunCompletedEvent,
    RunContentEvent,
    RunErrorEvent,
    RunStartedEvent,
    ToolCallStartedEvent,
)


def _agent_card() -> A2AAgentCard:
    """An Agent Card of an A2A v1.0 server that streams."""
    return A2AAgentCard(
        name="Test Agent",
        supported_interfaces=[
            AgentInterface(url="http://localhost:7777", protocol_binding="JSONRPC", protocol_version="1.0")
        ],
        capabilities=AgentCapabilities(streaming=True),
    )


def _status_update(state, metadata=None, text=None) -> StreamResponse:
    """A status-update event of the test task."""
    status = TaskStatus(state=state)
    if text:
        status.message.CopyFrom(Message(message_id="m-status", role=Role.ROLE_AGENT, parts=[Part(text=text)]))
    return StreamResponse(
        status_update=TaskStatusUpdateEvent(task_id="task-123", context_id="ctx-456", status=status, metadata=metadata)
    )


def _artifact_update(text, append=False, last_chunk=False) -> StreamResponse:
    """An artifact-update event carrying a chunk of the response."""
    return StreamResponse(
        artifact_update=TaskArtifactUpdateEvent(
            task_id="task-123",
            context_id="ctx-456",
            artifact=Artifact(artifact_id="task-123-response", name="response", parts=[Part(text=text)]),
            append=append,
            last_chunk=last_chunk,
        )
    )


def _task(state, text=None) -> StreamResponse:
    """The test task in the given state, with its response when given."""
    artifacts = [Artifact(artifact_id="task-123-response", name="response", parts=[Part(text=text)])] if text else []
    return StreamResponse(
        task=Task(id="task-123", context_id="ctx-456", status=TaskStatus(state=state), artifacts=artifacts)
    )


def _patch_sdk_client(responses: Optional[List[StreamResponse]] = None, error: Optional[Exception] = None):
    """Patch the A2A SDK client the A2AClient builds, to yield the given responses or raise the given error."""

    async def send_message(request):
        if error is not None:
            raise error
        for response in responses or []:
            yield response

    sdk_client = MagicMock()
    sdk_client.send_message = send_message
    factory = MagicMock()
    factory.create.return_value = sdk_client
    return patch("agno.client.a2a.client.ClientFactory", return_value=factory)


def _client() -> A2AClient:
    """An A2AClient that already holds the server's Agent Card."""
    client = A2AClient("http://localhost:7777")
    client._agent_card = _agent_card()
    return client


class TestA2AClientInit:
    """Test A2AClient initialization."""

    def test_init_default_values(self):
        """Test client initialization with default values."""
        client = A2AClient("http://localhost:7777")
        assert client.base_url == "http://localhost:7777"
        assert client.timeout == 30
        assert client.protocol == "rest"

    def test_init_custom_values(self):
        """Test client initialization with custom values."""
        client = A2AClient(
            "http://localhost:8080/",
            timeout=60,
            protocol="json-rpc",
        )
        assert client.base_url == "http://localhost:8080"  # Trailing slash stripped
        assert client.timeout == 60
        assert client.protocol == "json-rpc"

    def test_get_endpoint(self):
        """Test endpoint URL building."""
        client = A2AClient("http://localhost:7777")
        assert (
            client._get_endpoint("/.well-known/agent-card.json") == "http://localhost:7777/.well-known/agent-card.json"
        )

    def test_use_base_url(self):
        """Test the card's interfaces are pointed at the base URL."""
        client = A2AClient("http://gateway:7777/proxy/a2a/agents/support")
        agent_card = A2AAgentCard(
            supported_interfaces=[
                AgentInterface(url="http://localhost:7777/a2a/agents/support", protocol_binding="JSONRPC"),
            ]
        )

        client._use_base_url(agent_card)

        assert agent_card.supported_interfaces[0].url == "http://gateway:7777/proxy/a2a/agents/support"


class TestBuildMessage:
    """Test message building."""

    def test_basic_message(self):
        """Test building basic message."""
        client = A2AClient("http://localhost:7777")
        message = client._build_message(message="Hello")

        assert message.message_id
        assert message.role == Role.ROLE_USER
        assert message.parts[0].text == "Hello"

    def test_message_with_context(self):
        """Test building message with context ID."""
        client = A2AClient("http://localhost:7777")
        message = client._build_message(
            message="Hello",
            context_id="session-123",
            user_id="user-456",
        )

        assert message.context_id == "session-123"
        assert message.metadata["userId"] == "user-456"


class TestParseTaskResult:
    """Test task result parsing."""

    def test_parse_basic_response(self):
        """Test parsing basic A2A response."""
        client = A2AClient("http://localhost:7777")

        result = client._parse_task_result(_task(TaskState.TASK_STATE_COMPLETED, text="Hello, world!"))

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
        response = _task(TaskState.TASK_STATE_FAILED)
        response.task.status.message.CopyFrom(
            Message(message_id="m1", role=Role.ROLE_AGENT, parts=[Part(text="Error: boom")])
        )

        result = client._parse_task_result(response)

        assert result.status == "failed"
        assert result.is_failed
        assert result.content == "Error: boom"

    def test_parse_with_artifacts(self):
        """Test parsing response with file artifacts."""
        client = A2AClient("http://localhost:7777")
        response = _task(TaskState.TASK_STATE_COMPLETED, text="Here is the image")
        response.task.artifacts.append(
            Artifact(
                artifact_id="image-0",
                name="image-0",
                parts=[Part(url="https://example.com/image.png", media_type="image/png")],
            )
        )

        result = client._parse_task_result(response)

        assert result.content == "Here is the image"
        assert len(result.artifacts) == 1
        assert result.artifacts[0].artifact_id == "image-0"
        assert result.artifacts[0].uri == "https://example.com/image.png"
        assert result.artifacts[0].mime_type == "image/png"

    def test_parse_structured_response(self):
        """Test parsing response with structured content."""
        client = A2AClient("http://localhost:7777")
        response = _task(TaskState.TASK_STATE_COMPLETED)
        data_part = Part(media_type="application/json")
        data_part.data.struct_value.update({"city": "Paris"})
        response.task.artifacts.append(Artifact(artifact_id="task-123-response", name="response", parts=[data_part]))

        result = client._parse_task_result(response)

        assert result.data == {"city": "Paris"}
        # Structured content with no text is also given as its JSON string
        assert result.content == '{"city": "Paris"}'


class TestParseStreamEvent:
    """Test stream event parsing."""

    def test_parse_content_event(self):
        """Test parsing content event."""
        client = A2AClient("http://localhost:7777")

        event = client._parse_stream_event(_artifact_update("Hello"))

        assert isinstance(event, StreamEvent)
        assert event.event_type == "content"
        assert event.content == "Hello"
        assert event.task_id == "task-123"
        assert event.is_content
        assert not event.is_final

    def test_parse_status_event(self):
        """Test parsing status event."""
        client = A2AClient("http://localhost:7777")

        event = client._parse_stream_event(_status_update(TaskState.TASK_STATE_WORKING))

        assert event.event_type == "working"
        assert event.task_id == "task-123"
        assert not event.is_final

    def test_parse_tool_call_event(self):
        """Test parsing tool call event."""
        client = A2AClient("http://localhost:7777")

        event = client._parse_stream_event(
            _status_update(
                TaskState.TASK_STATE_WORKING, metadata={"agno_event_type": "tool_call_started", "tool_name": "add"}
            )
        )

        assert event.is_tool_call
        assert event.metadata["tool_name"] == "add"

    def test_parse_completed_event(self):
        """Test parsing completed event."""
        client = A2AClient("http://localhost:7777")

        event = client._parse_stream_event(_status_update(TaskState.TASK_STATE_COMPLETED))

        assert event.event_type == "completed"
        assert event.is_completed
        assert event.is_final


class TestSendMessage:
    """Test send_message method."""

    @pytest.mark.asyncio
    async def test_send_message_success(self):
        """Test successful message send."""
        with _patch_sdk_client([_task(TaskState.TASK_STATE_COMPLETED, text="The answer is 4")]):
            client = _client()
            result = await client.send_message(
                message="What is 2 + 2?",
            )

            assert result.content == "The answer is 4"
            assert result.is_completed

    @pytest.mark.asyncio
    async def test_send_message_fetches_agent_card(self):
        """Test send_message negotiates the protocol from the server's Agent Card."""
        with (
            patch("agno.client.a2a.client.get_default_async_client") as mock_get_client,
            _patch_sdk_client([_task(TaskState.TASK_STATE_COMPLETED, text="Hi")]) as mock_factory,
        ):
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "name": "Test Agent",
                "url": "http://localhost:7777",
                "protocolVersion": "0.3.0",
                "capabilities": {"streaming": True},
            }
            mock_http_client = AsyncMock()
            mock_http_client.get.return_value = mock_response
            mock_get_client.return_value = mock_http_client

            client = A2AClient("http://localhost:7777")
            await client.send_message(message="Hello")

            mock_http_client.get.assert_called_once()
            assert mock_http_client.get.call_args.args[0] == "http://localhost:7777/.well-known/agent-card.json"
            agent_card = mock_factory.return_value.create.call_args.args[0]
            assert agent_card.supported_interfaces[0].protocol_version == "0.3.0"

    @pytest.mark.asyncio
    async def test_send_message_http_error(self):
        """Test send_message with HTTP error."""
        mock_response = Response(404, request=Request("POST", "http://test"))
        http_error = HTTPStatusError("Not Found", request=mock_response.request, response=mock_response)
        sdk_error = A2AClientError("HTTP Error 404: Not Found")
        sdk_error.__cause__ = http_error

        with _patch_sdk_client(error=sdk_error):
            client = _client()
            with pytest.raises(HTTPStatusError) as exc_info:
                await client.send_message(
                    message="Hello",
                )
            assert exc_info.value.response.status_code == 404

    @pytest.mark.asyncio
    async def test_send_message_connection_error(self):
        """Test send_message with connection error."""
        sdk_error = A2AClientError("Network communication error")
        sdk_error.__cause__ = ConnectError("Connection refused")

        with _patch_sdk_client(error=sdk_error):
            client = _client()
            with pytest.raises(RemoteServerUnavailableError) as exc_info:
                await client.send_message(
                    message="Hello",
                )
            assert "Failed to connect" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_send_message_timeout(self):
        """Test send_message with timeout."""
        with _patch_sdk_client(error=A2AClientTimeoutError("Client Request timed out")):
            client = _client()
            with pytest.raises(RemoteServerUnavailableError) as exc_info:
                await client.send_message(
                    message="Hello",
                )
            assert "timed out" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_send_message_failed_task_returns_result(self):
        """Test send_message returns the result of a failed task instead of raising."""
        with _patch_sdk_client([_task(TaskState.TASK_STATE_FAILED)]):
            client = _client()
            result = await client.send_message(
                message="Hello",
            )

            assert result.is_failed


class TestTaskMethods:
    """Test get_task and cancel_task methods."""

    @pytest.mark.asyncio
    async def test_get_task_success(self):
        """Test reading a task by its id."""
        sdk_client = MagicMock()
        sdk_client.get_task = AsyncMock(return_value=_task(TaskState.TASK_STATE_WORKING).task)
        factory = MagicMock()
        factory.create.return_value = sdk_client

        with patch("agno.client.a2a.client.ClientFactory", return_value=factory):
            client = _client()
            result = await client.get_task("task-123")

            assert result.task_id == "task-123"
            assert result.status == "working"
            assert sdk_client.get_task.call_args.args[0].id == "task-123"

    @pytest.mark.asyncio
    async def test_cancel_task_success(self):
        """Test cancelling a task by its id."""
        sdk_client = MagicMock()
        sdk_client.cancel_task = AsyncMock(return_value=_task(TaskState.TASK_STATE_CANCELED).task)
        factory = MagicMock()
        factory.create.return_value = sdk_client

        with patch("agno.client.a2a.client.ClientFactory", return_value=factory):
            client = _client()
            result = await client.cancel_task("task-123")

            assert result.is_canceled
            assert sdk_client.cancel_task.call_args.args[0].id == "task-123"


class TestStreamMessage:
    """Test stream_message method."""

    @pytest.mark.asyncio
    async def test_stream_message_success(self):
        """Test successful message streaming."""
        responses = [
            _status_update(TaskState.TASK_STATE_WORKING),
            _artifact_update("Hello"),
            _artifact_update(" World", append=True),
            _artifact_update("Hello World", last_chunk=True),
            _status_update(TaskState.TASK_STATE_COMPLETED),
        ]
        with _patch_sdk_client(responses):
            events = []
            client = _client()
            async for event in client.stream_message(
                message="Hello",
            ):
                events.append(event)

            assert len(events) == 5
            # Check content events
            content_events = [e for e in events if e.is_content]
            assert len(content_events) == 2
            assert content_events[0].content == "Hello"
            assert content_events[1].content == " World"
            # The complete response closes the streamed artifact; it is not content again
            assert events[3].event_type == "artifact"
            assert events[3].content == "Hello World"

    @pytest.mark.asyncio
    async def test_stream_message_terminal_status_update_carries_metadata(self):
        """Regression test: out-of-band metadata rides the terminal status-update
        (the A2A spec's terminal event). map_stream_events_to_run_events must read
        event.metadata off that terminal event and forward it onto RunCompletedEvent,
        rather than dropping it."""
        responses = [
            _status_update(TaskState.TASK_STATE_WORKING),
            _artifact_update("Hello"),
            _status_update(TaskState.TASK_STATE_COMPLETED, metadata={"refetch_model": True}),
        ]
        with _patch_sdk_client(responses):
            client = _client()

            async def raw_stream() -> AsyncIterator[StreamEvent]:
                async for event in client.stream_message(message="Hello"):
                    yield event

            run_events = [event async for event in map_stream_events_to_run_events(raw_stream(), agent_id="agent-1")]

            assert [type(e) for e in run_events] == [
                RunStartedEvent,
                RunContentEvent,
                RunCompletedEvent,
            ]
            completed = run_events[-1]
            assert completed.content == "Hello"
            assert completed.metadata == {"refetch_model": True}

    @pytest.mark.asyncio
    async def test_stream_message_maps_tool_calls_and_failure(self):
        """Test a tool call and a failed run map to their Agno run events."""
        responses = [
            _status_update(TaskState.TASK_STATE_WORKING),
            _status_update(
                TaskState.TASK_STATE_WORKING,
                metadata={"agno_event_type": "tool_call_started", "tool_name": "add", "tool_args": '{"a": 1}'},
            ),
            _status_update(TaskState.TASK_STATE_FAILED, text="Error: boom"),
        ]
        with _patch_sdk_client(responses):
            client = _client()

            async def raw_stream() -> AsyncIterator[StreamEvent]:
                async for event in client.stream_message(message="Hello"):
                    yield event

            run_events = [event async for event in map_stream_events_to_run_events(raw_stream(), agent_id="agent-1")]

            assert [type(e) for e in run_events] == [
                RunStartedEvent,
                ToolCallStartedEvent,
                RunErrorEvent,
            ]
            assert run_events[1].tool.tool_name == "add"
            assert run_events[1].tool.tool_args == {"a": 1}
            assert run_events[-1].content == "Error: boom"


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
