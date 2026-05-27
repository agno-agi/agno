import json
from typing import AsyncIterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.models.response import ToolExecution
from agno.os.app import AgentOS
from agno.os.interfaces.a2a import A2A
from agno.run.agent import (
    MemoryUpdateCompletedEvent,
    MemoryUpdateStartedEvent,
    ReasoningCompletedEvent,
    ReasoningStartedEvent,
    ReasoningStepEvent,
    RunCancelledEvent,
    RunCompletedEvent,
    RunContentEvent,
    RunOutput,
    RunOutputEvent,
    RunStartedEvent,
    RunStatus,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.run.workflow import (
    StepCompletedEvent as WorkflowStepCompletedEvent,
)
from agno.run.workflow import (
    StepStartedEvent as WorkflowStepStartedEvent,
)
from agno.run.workflow import (
    WorkflowCompletedEvent,
    WorkflowRunOutput,
    WorkflowStartedEvent,
)
from agno.team import Team
from agno.workflow import Workflow


@pytest.fixture
def test_agent():
    """Create a test agent for A2A."""
    return Agent(name="test-a2a-agent", instructions="You are a helpful assistant.")


@pytest.fixture
def test_client(test_agent: Agent):
    """Create a FastAPI test client with A2A interface."""
    agent_os = AgentOS(agents=[test_agent], a2a_interface=True)
    app = agent_os.get_app()
    return TestClient(app)


def test_a2a_interface_parameter():
    """Test that the A2A interface is setup correctly using the a2a_interface parameter."""
    agent = Agent()
    agent_os = AgentOS(agents=[agent], a2a_interface=True)
    app = agent_os.get_app()

    assert app is not None
    assert any([isinstance(interface, A2A) for interface in agent_os.interfaces])
    assert "/a2a/agents/{id}/v1/message:send" in [route.path for route in app.routes]  # type: ignore
    assert "/a2a/agents/{id}/v1/message:stream" in [route.path for route in app.routes]  # type: ignore


def test_a2a_interface_in_interfaces_parameter():
    """Test that the A2A interface is setup correctly using the interfaces parameter."""
    interface_agent = Agent(name="interface-agent")
    os_agent = Agent(name="os-agent")
    agent_os = AgentOS(agents=[os_agent], interfaces=[A2A(agents=[interface_agent])])
    app = agent_os.get_app()

    assert app is not None
    assert any([isinstance(interface, A2A) for interface in agent_os.interfaces])
    assert "/a2a/agents/{id}/v1/message:send" in [route.path for route in app.routes]  # type: ignore
    assert "/a2a/agents/{id}/v1/message:stream" in [route.path for route in app.routes]  # type: ignore


def test_a2a(test_agent: Agent, test_client: TestClient):
    """Test the basic non-streaming A2A flow."""

    mock_output = RunOutput(
        run_id="test-run-123",
        session_id="context-789",
        agent_id=test_agent.id,
        agent_name=test_agent.name,
        content="Hello! This is a test response.",
        status=RunStatus.completed,
    )

    with patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_output

        request_body = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "id": "request-123",
            "params": {
                "message": {
                    "messageId": "msg-123",
                    "role": "user",
                    "contextId": "context-789",
                    "parts": [{"kind": "text", "text": "Hello, agent!"}],
                }
            },
        }

        response = test_client.post(f"/a2a/agents/{test_agent.id}/v1/message:send", json=request_body)

        assert response.status_code == 200
        data = response.json()

        assert data["jsonrpc"] == "2.0"
        assert data["id"] == "request-123"
        assert "result" in data

        task = data["result"]
        assert task["id"] == "test-run-123"
        assert task["contextId"] == "context-789"
        assert task["status"]["state"] == "completed"
        assert len(task["history"]) == 1

        message = task["history"][0]
        assert message["role"] == "agent"
        assert len(message["parts"]) == 1
        assert message["parts"][0]["kind"] == "text"
        assert message["parts"][0]["text"] == "Hello! This is a test response."

        mock_arun.assert_called_once()
        call_kwargs = mock_arun.call_args.kwargs
        assert call_kwargs["input"] == "Hello, agent!"
        assert call_kwargs["session_id"] == "context-789"


def test_a2a_streaming(test_agent: Agent, test_client: TestClient):
    """Test the basic streaming A2A flow."""

    async def mock_event_stream() -> AsyncIterator[RunOutputEvent]:
        yield RunStartedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
        )

        yield RunContentEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
            content="Hello! ",
        )

        yield RunContentEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
            content="This is ",
        )

        yield RunContentEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
            content="a streaming response.",
        )

        yield RunCompletedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
            content="Hello! this is a streaming response.",
        )

    with patch.object(test_agent, "arun") as mock_arun:
        mock_arun.return_value = mock_event_stream()

        request_body = {
            "jsonrpc": "2.0",
            "method": "message/stream",
            "id": "request-123",
            "params": {
                "message": {
                    "messageId": "msg-123",
                    "role": "user",
                    "contextId": "context-789",
                    "parts": [{"kind": "text", "text": "Hello, agent!"}],
                }
            },
        }

        response = test_client.post(f"/a2a/agents/{test_agent.id}/v1/message:stream", json=request_body)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        # Parse SSE format: "event: EventType\ndata: JSON\n\n"
        events = []
        for chunk in response.text.split("\n\n"):
            if chunk.strip():
                lines = chunk.strip().split("\n")
                for line in lines:
                    if line.startswith("data: "):
                        events.append(json.loads(line[6:]))

        assert len(events) >= 5

        assert events[0]["result"]["kind"] == "status-update"
        assert events[0]["result"]["status"]["state"] == "working"
        assert events[0]["result"]["taskId"] == "test-run-123"
        assert events[0]["result"]["contextId"] == "context-789"

        content_messages = [e for e in events if e["result"].get("kind") == "message" and e["result"].get("parts")]
        assert len(content_messages) == 3
        assert content_messages[0]["result"]["parts"][0]["text"] == "Hello! "
        assert content_messages[1]["result"]["parts"][0]["text"] == "This is "
        assert content_messages[2]["result"]["parts"][0]["text"] == "a streaming response."

        for msg in content_messages:
            assert msg["result"]["metadata"]["agno_content_category"] == "content"
            assert msg["result"]["role"] == "agent"

        final_status_events = [
            e for e in events if e["result"].get("kind") == "status-update" and e["result"].get("final") is True
        ]
        assert len(final_status_events) == 1
        assert final_status_events[0]["result"]["status"]["state"] == "completed"

        final_task = events[-1]
        assert final_task["id"] == "request-123"
        assert final_task["result"]["contextId"] == "context-789"
        assert final_task["result"]["status"]["state"] == "completed"
        assert final_task["result"]["history"][0]["parts"][0]["text"] == "Hello! this is a streaming response."

        mock_arun.assert_called_once()
        call_kwargs = mock_arun.call_args.kwargs
        assert call_kwargs["input"] == "Hello, agent!"
        assert call_kwargs["session_id"] == "context-789"
        assert call_kwargs["stream"] is True
        assert call_kwargs["stream_events"] is True


def test_a2a_streaming_with_tools(test_agent: Agent, test_client: TestClient):
    """Test A2A streaming flow with tool events."""

    async def mock_event_stream() -> AsyncIterator[RunOutputEvent]:
        """Mock event stream with tool calls."""
        yield RunStartedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
        )

        yield ToolCallStartedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
            tool=ToolExecution(tool_name="get_weather", tool_args={"location": "Shanghai"}),
        )

        yield ToolCallCompletedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
            tool=ToolExecution(tool_name="get_weather", tool_args={"location": "Shanghai"}),
            content="72°F and sunny",
        )

        yield RunContentEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
            content="The weather in Shanghai is 72°F and sunny.",
        )

        yield RunCompletedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
            content="The weather in Shanghai is 72°F and sunny.",
        )

    with patch.object(test_agent, "arun") as mock_arun:
        mock_arun.return_value = mock_event_stream()

        request_body = {
            "jsonrpc": "2.0",
            "method": "message/stream",
            "id": "request-123",
            "params": {
                "message": {
                    "messageId": "msg-123",
                    "role": "user",
                    "contextId": "context-789",
                    "parts": [{"kind": "text", "text": "What's the weather in SF?"}],
                }
            },
        }

        response = test_client.post(f"/a2a/agents/{test_agent.id}/v1/message:stream", json=request_body)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        # Parse SSE format: "event: EventType\ndata: JSON\n\n"
        events = []
        for chunk in response.text.split("\n\n"):
            if chunk.strip():
                lines = chunk.strip().split("\n")
                for line in lines:
                    if line.startswith("data: "):
                        events.append(json.loads(line[6:]))

        tool_started = [
            e for e in events if e["result"].get("metadata", {}).get("agno_event_type") == "tool_call_started"
        ]
        assert len(tool_started) == 1
        assert tool_started[0]["result"]["kind"] == "status-update"
        assert tool_started[0]["result"]["status"]["state"] == "working"
        assert tool_started[0]["result"]["metadata"]["tool_name"] == "get_weather"
        tool_args = json.loads(tool_started[0]["result"]["metadata"]["tool_args"])
        assert tool_args == {"location": "Shanghai"}

        tool_completed = [
            e for e in events if e["result"].get("metadata", {}).get("agno_event_type") == "tool_call_completed"
        ]
        assert len(tool_completed) == 1
        assert tool_completed[0]["result"]["kind"] == "status-update"
        assert tool_completed[0]["result"]["metadata"]["tool_name"] == "get_weather"

        content_messages = [e for e in events if e["result"].get("kind") == "message" and e["result"].get("parts")]
        assert len(content_messages) == 1
        assert content_messages[0]["result"]["parts"][0]["text"] == "The weather in Shanghai is 72°F and sunny."
        assert content_messages[0]["result"]["metadata"]["agno_content_category"] == "content"

        final_task = events[-1]
        assert final_task["result"]["kind"] == "task"
        assert final_task["result"]["status"]["state"] == "completed"
        assert final_task["result"]["history"][0]["parts"][0]["text"] == "The weather in Shanghai is 72°F and sunny."


def test_a2a_streaming_with_reasoning(test_agent: Agent, test_client: TestClient):
    """Test A2A streaming with reasoning events."""

    async def mock_event_stream() -> AsyncIterator[RunOutputEvent]:
        """Mock event stream with reasoning."""
        yield RunStartedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
        )

        yield ReasoningStartedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
        )

        yield ReasoningStepEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
            reasoning_content="First, I need to understand what the user is asking...",
            content_type="str",
        )

        yield ReasoningStepEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
            reasoning_content="Then I should formulate a clear response.",
            content_type="str",
        )

        yield ReasoningCompletedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
        )

        yield RunContentEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
            content="Based on my analysis, here's the answer.",
        )

        yield RunCompletedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
            content="Based on my analysis, here's the answer.",
        )

    with patch.object(test_agent, "arun") as mock_arun:
        mock_arun.return_value = mock_event_stream()

        request_body = {
            "jsonrpc": "2.0",
            "method": "message/stream",
            "id": "request-123",
            "params": {
                "message": {
                    "messageId": "msg-123",
                    "role": "user",
                    "contextId": "context-789",
                    "parts": [{"kind": "text", "text": "Help me think through this problem."}],
                }
            },
        }

        response = test_client.post(f"/a2a/agents/{test_agent.id}/v1/message:stream", json=request_body)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        # Parse SSE format: "event: EventType\ndata: JSON\n\n"
        events = []
        for chunk in response.text.split("\n\n"):
            if chunk.strip():
                lines = chunk.strip().split("\n")
                for line in lines:
                    if line.startswith("data: "):
                        events.append(json.loads(line[6:]))

        reasoning_started = [
            e for e in events if e["result"].get("metadata", {}).get("agno_event_type") == "reasoning_started"
        ]
        assert len(reasoning_started) == 1
        assert reasoning_started[0]["result"]["kind"] == "status-update"
        assert reasoning_started[0]["result"]["status"]["state"] == "working"

        reasoning_messages = [
            e
            for e in events
            if e["result"].get("kind") == "message"
            and e["result"].get("metadata", {}).get("agno_content_category") == "reasoning"
        ]
        assert len(reasoning_messages) == 2
        assert (
            reasoning_messages[0]["result"]["parts"][0]["text"]
            == "First, I need to understand what the user is asking..."
        )
        assert reasoning_messages[1]["result"]["parts"][0]["text"] == "Then I should formulate a clear response."

        for msg in reasoning_messages:
            assert msg["result"]["metadata"]["agno_content_category"] == "reasoning"
            assert msg["result"]["metadata"]["agno_event_type"] == "reasoning_step"

        reasoning_completed = [
            e for e in events if e["result"].get("metadata", {}).get("agno_event_type") == "reasoning_completed"
        ]
        assert len(reasoning_completed) == 1
        assert reasoning_completed[0]["result"]["kind"] == "status-update"

        content_messages = [
            e
            for e in events
            if e["result"].get("kind") == "message"
            and e["result"].get("metadata", {}).get("agno_content_category") == "content"
        ]
        assert len(content_messages) == 1
        assert content_messages[0]["result"]["parts"][0]["text"] == "Based on my analysis, here's the answer."

        final_task = events[-1]
        assert final_task["result"]["kind"] == "task"
        assert final_task["result"]["status"]["state"] == "completed"
        assert final_task["result"]["history"][0]["parts"][0]["text"] == "Based on my analysis, here's the answer."


def test_a2a_streaming_with_memory(test_agent: Agent, test_client: TestClient):
    """Test A2A streaming with memory update events."""

    async def mock_event_stream() -> AsyncIterator[RunOutputEvent]:
        yield RunStartedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
        )

        yield MemoryUpdateStartedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
        )

        yield MemoryUpdateCompletedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
        )

        yield RunContentEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
            content="I've updated my memory with this information.",
        )

        yield RunCompletedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
        )

    with patch.object(test_agent, "arun") as mock_arun:
        mock_arun.return_value = mock_event_stream()

        request_body = {
            "jsonrpc": "2.0",
            "method": "message/stream",
            "id": "request-123",
            "params": {
                "message": {
                    "messageId": "msg-123",
                    "role": "user",
                    "contextId": "context-789",
                    "parts": [{"kind": "text", "text": "Remember this for later."}],
                }
            },
        }

        response = test_client.post(f"/a2a/agents/{test_agent.id}/v1/message:stream", json=request_body)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        # Parse SSE format: "event: EventType\ndata: JSON\n\n"
        events = []
        for chunk in response.text.split("\n\n"):
            if chunk.strip():
                lines = chunk.strip().split("\n")
                for line in lines:
                    if line.startswith("data: "):
                        events.append(json.loads(line[6:]))

        memory_started = [
            e for e in events if e["result"].get("metadata", {}).get("agno_event_type") == "memory_update_started"
        ]
        assert len(memory_started) == 1
        assert memory_started[0]["result"]["kind"] == "status-update"
        assert memory_started[0]["result"]["status"]["state"] == "working"

        memory_completed = [
            e for e in events if e["result"].get("metadata", {}).get("agno_event_type") == "memory_update_completed"
        ]
        assert len(memory_completed) == 1
        assert memory_completed[0]["result"]["kind"] == "status-update"

        content_messages = [
            e
            for e in events
            if e["result"].get("kind") == "message"
            and e["result"].get("metadata", {}).get("agno_content_category") == "content"
        ]
        assert len(content_messages) == 1
        assert content_messages[0]["result"]["parts"][0]["text"] == "I've updated my memory with this information."

        final_task = events[-1]
        assert final_task["result"]["kind"] == "task"
        assert final_task["result"]["status"]["state"] == "completed"
        assert final_task["result"]["history"][0]["parts"][0]["text"] == "I've updated my memory with this information."


@pytest.fixture
def test_team():
    """Create a test team for A2A."""
    agent1 = Agent(name="agent1", instructions="You are agent 1.")
    agent2 = Agent(name="agent2", instructions="You are agent 2.")
    return Team(name="test-a2a-team", members=[agent1, agent2], instructions="You are a helpful team.")


@pytest.fixture
def test_team_client(test_team: Team):
    """Create a FastAPI test client with A2A interface for teams."""
    agent_os = AgentOS(teams=[test_team], a2a_interface=True)
    app = agent_os.get_app()
    return TestClient(app)


def test_a2a_team(test_team: Team, test_team_client: TestClient):
    """Test the basic non-streaming A2A flow with a Team."""

    mock_output = RunOutput(
        run_id="test-run-123",
        session_id="context-789",
        agent_id=test_team.id,
        agent_name=test_team.name,
        content="Hello! This is a test response from the team.",
        status=RunStatus.completed,
    )

    with patch.object(test_team, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_output

        request_body = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "id": "request-123",
            "params": {
                "message": {
                    "messageId": "msg-123",
                    "role": "user",
                    "contextId": "context-789",
                    "parts": [{"kind": "text", "text": "Hello, team!"}],
                }
            },
        }

        response = test_team_client.post(f"/a2a/teams/{test_team.id}/v1/message:send", json=request_body)

        assert response.status_code == 200
        data = response.json()

        assert data["jsonrpc"] == "2.0"
        assert data["id"] == "request-123"
        assert "result" in data

        task = data["result"]
        assert task["id"] == "test-run-123"
        assert task["contextId"] == "context-789"
        assert task["status"]["state"] == "completed"
        assert len(task["history"]) == 1

        message = task["history"][0]
        assert message["role"] == "agent"
        assert len(message["parts"]) == 1
        assert message["parts"][0]["kind"] == "text"
        assert message["parts"][0]["text"] == "Hello! This is a test response from the team."

        mock_arun.assert_called_once()
        call_kwargs = mock_arun.call_args.kwargs
        assert call_kwargs["input"] == "Hello, team!"
        assert call_kwargs["session_id"] == "context-789"


def test_a2a_streaming_team(test_team: Team, test_team_client: TestClient):
    """Test the basic streaming A2A flow with a Team."""

    async def mock_event_stream() -> AsyncIterator[RunOutputEvent]:
        yield RunStartedEvent(
            session_id="context-789",
            agent_id=test_team.id,
            agent_name=test_team.name,
            run_id="test-run-123",
        )

        yield RunContentEvent(
            session_id="context-789",
            agent_id=test_team.id,
            agent_name=test_team.name,
            run_id="test-run-123",
            content="Hello! ",
        )

        yield RunContentEvent(
            session_id="context-789",
            agent_id=test_team.id,
            agent_name=test_team.name,
            run_id="test-run-123",
            content="This is ",
        )

        yield RunContentEvent(
            session_id="context-789",
            agent_id=test_team.id,
            agent_name=test_team.name,
            run_id="test-run-123",
            content="a streaming response from the team.",
        )

        yield RunCompletedEvent(
            session_id="context-789",
            agent_id=test_team.id,
            agent_name=test_team.name,
            run_id="test-run-123",
            content="Hello! this is a streaming response from the team.",
        )

    with patch.object(test_team, "arun") as mock_arun:
        mock_arun.return_value = mock_event_stream()

        request_body = {
            "jsonrpc": "2.0",
            "method": "message/stream",
            "id": "request-123",
            "params": {
                "message": {
                    "messageId": "msg-123",
                    "role": "user",
                    "contextId": "context-789",
                    "parts": [{"kind": "text", "text": "Hello, team!"}],
                }
            },
        }

        response = test_team_client.post(f"/a2a/teams/{test_team.id}/v1/message:stream", json=request_body)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        # Parse SSE format: "event: EventType\ndata: JSON\n\n"
        events = []
        for chunk in response.text.split("\n\n"):
            if chunk.strip():
                lines = chunk.strip().split("\n")
                for line in lines:
                    if line.startswith("data: "):
                        events.append(json.loads(line[6:]))

        assert len(events) >= 5

        assert events[0]["result"]["kind"] == "status-update"
        assert events[0]["result"]["status"]["state"] == "working"
        assert events[0]["result"]["taskId"] == "test-run-123"
        assert events[0]["result"]["contextId"] == "context-789"

        content_messages = [e for e in events if e["result"].get("kind") == "message" and e["result"].get("parts")]
        assert len(content_messages) == 3
        assert content_messages[0]["result"]["parts"][0]["text"] == "Hello! "
        assert content_messages[1]["result"]["parts"][0]["text"] == "This is "
        assert content_messages[2]["result"]["parts"][0]["text"] == "a streaming response from the team."

        for msg in content_messages:
            assert msg["result"]["metadata"]["agno_content_category"] == "content"
            assert msg["result"]["role"] == "agent"

        final_status_events = [
            e for e in events if e["result"].get("kind") == "status-update" and e["result"].get("final") is True
        ]
        assert len(final_status_events) == 1
        assert final_status_events[0]["result"]["status"]["state"] == "completed"

        final_task = events[-1]
        assert final_task["id"] == "request-123"
        assert final_task["result"]["contextId"] == "context-789"
        assert final_task["result"]["status"]["state"] == "completed"
        assert (
            final_task["result"]["history"][0]["parts"][0]["text"]
            == "Hello! this is a streaming response from the team."
        )

        mock_arun.assert_called_once()
        call_kwargs = mock_arun.call_args.kwargs
        assert call_kwargs["input"] == "Hello, team!"
        assert call_kwargs["session_id"] == "context-789"
        assert call_kwargs["stream"] is True
        assert call_kwargs["stream_events"] is True


def test_a2a_user_id_from_header(test_agent: Agent, test_client: TestClient):
    """Test that user_id is extracted from X-User-ID header and passed to arun()."""
    mock_output = RunOutput(
        run_id="test-run-123",
        session_id="context-789",
        agent_id=test_agent.id,
        agent_name=test_agent.name,
        content="Response",
    )

    with patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_output

        request_body = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "id": "request-123",
            "params": {
                "message": {
                    "messageId": "msg-123",
                    "role": "user",
                    "parts": [{"kind": "text", "text": "Hello!"}],
                }
            },
        }

        response = test_client.post(
            f"/a2a/agents/{test_agent.id}/v1/message:send", json=request_body, headers={"X-User-ID": "user-456"}
        )

        assert response.status_code == 200
        mock_arun.assert_called_once()
        call_kwargs = mock_arun.call_args.kwargs
        assert call_kwargs["user_id"] == "user-456"


def test_a2a_user_id_from_metadata(test_agent: Agent, test_client: TestClient):
    """Test that user_id is extracted from params.message.metadata as fallback."""
    mock_output = RunOutput(
        run_id="test-run-123",
        session_id="context-789",
        agent_id=test_agent.id,
        agent_name=test_agent.name,
        content="Response",
    )

    with patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_output

        request_body = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "id": "request-123",
            "params": {
                "message": {
                    "messageId": "msg-123",
                    "role": "user",
                    "metadata": {"userId": "user-789"},
                    "parts": [{"kind": "text", "text": "Hello!"}],
                }
            },
        }

        response = test_client.post(f"/a2a/agents/{test_agent.id}/v1/message:send", json=request_body)

        assert response.status_code == 200
        mock_arun.assert_called_once()
        call_kwargs = mock_arun.call_args.kwargs
        assert call_kwargs["user_id"] == "user-789"


def test_a2a_error_handling_non_streaming(test_agent: Agent, test_client: TestClient):
    """Test that errors during agent run return Task with failed status."""

    with patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.side_effect = Exception("Agent execution failed")

        request_body = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "id": "request-123",
            "params": {
                "message": {
                    "messageId": "msg-123",
                    "role": "user",
                    "contextId": "context-789",
                    "parts": [{"kind": "text", "text": "Hello!"}],
                }
            },
        }

        response = test_client.post(f"/a2a/agents/{test_agent.id}/v1/message:send", json=request_body)

        assert response.status_code == 200
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == "request-123"
        assert data["result"]["status"]["state"] == "failed"
        assert data["result"]["contextId"] == "context-789"
        assert len(data["result"]["history"]) == 1
        assert "Agent execution failed" in data["result"]["history"][0]["parts"][0]["text"]


def test_a2a_streaming_with_media_artifacts(test_agent: Agent, test_client: TestClient):
    """Test that media outputs from RunCompletedEvent are mapped to A2A Artifacts."""

    async def mock_event_stream() -> AsyncIterator[RunOutputEvent]:
        from agno.media import Audio, Image, Video

        yield RunStartedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
        )

        yield RunContentEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
            content="Generated image",
        )

        yield RunCompletedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
            content="Generated image",
            images=[Image(url="https://example.com/image.png")],
            videos=[Video(url="https://example.com/video.mp4")],
            audio=[Audio(url="https://example.com/audio.mp3")],
        )

    with patch.object(test_agent, "arun") as mock_arun:
        mock_arun.return_value = mock_event_stream()

        request_body = {
            "jsonrpc": "2.0",
            "method": "message/stream",
            "id": "request-123",
            "params": {
                "message": {
                    "messageId": "msg-123",
                    "role": "user",
                    "contextId": "context-789",
                    "parts": [{"kind": "text", "text": "Generate media"}],
                }
            },
        }

        response = test_client.post(f"/a2a/agents/{test_agent.id}/v1/message:stream", json=request_body)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        # Parse SSE format: "event: EventType\ndata: JSON\n\n"
        events = []
        for chunk in response.text.split("\n\n"):
            if chunk.strip():
                lines = chunk.strip().split("\n")
                for line in lines:
                    if line.startswith("data: "):
                        events.append(json.loads(line[6:]))

        final_task = events[-1]
        assert final_task["result"]["kind"] == "task"
        assert final_task["result"]["status"]["state"] == "completed"

        artifacts = final_task["result"].get("artifacts")
        assert artifacts is not None
        assert len(artifacts) == 3

        image_artifact = next((a for a in artifacts if "image" in a["artifactId"]), None)
        assert image_artifact is not None
        assert image_artifact["name"] == "image-0"
        assert image_artifact["parts"][0]["file"]["uri"] == "https://example.com/image.png"

        video_artifact = next((a for a in artifacts if "video" in a["artifactId"]), None)
        assert video_artifact is not None
        assert video_artifact["name"] == "video-0"
        assert video_artifact["parts"][0]["file"]["uri"] == "https://example.com/video.mp4"

        audio_artifact = next((a for a in artifacts if "audio" in a["artifactId"]), None)
        assert audio_artifact is not None
        assert audio_artifact["name"] == "audio-0"
        assert audio_artifact["parts"][0]["file"]["uri"] == "https://example.com/audio.mp3"


def test_a2a_streaming_with_cancellation(test_agent: Agent, test_client: TestClient):
    """Test A2A streaming with run cancellation."""

    async def mock_event_stream() -> AsyncIterator[RunOutputEvent]:
        yield RunStartedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
        )

        yield RunContentEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
            content="Starting to process...",
        )

        yield RunCancelledEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
            reason="User requested cancellation",
        )

    with patch.object(test_agent, "arun") as mock_arun:
        mock_arun.return_value = mock_event_stream()

        request_body = {
            "jsonrpc": "2.0",
            "method": "message/stream",
            "id": "request-123",
            "params": {
                "message": {
                    "messageId": "msg-123",
                    "role": "user",
                    "contextId": "context-789",
                    "parts": [{"kind": "text", "text": "Start processing"}],
                }
            },
        }

        response = test_client.post(f"/a2a/agents/{test_agent.id}/v1/message:stream", json=request_body)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        # Parse SSE format: "event: EventType\ndata: JSON\n\n"
        events = []
        for chunk in response.text.split("\n\n"):
            if chunk.strip():
                lines = chunk.strip().split("\n")
                for line in lines:
                    if line.startswith("data: "):
                        events.append(json.loads(line[6:]))

        content_messages = [
            e
            for e in events
            if e["result"].get("kind") == "message"
            and e["result"].get("metadata", {}).get("agno_content_category") == "content"
        ]
        assert len(content_messages) == 1
        assert content_messages[0]["result"]["parts"][0]["text"] == "Starting to process..."

        final_status_events = [
            e for e in events if e["result"].get("kind") == "status-update" and e["result"].get("final") is True
        ]
        assert len(final_status_events) == 1
        assert final_status_events[0]["result"]["status"]["state"] == "canceled"
        assert final_status_events[0]["result"]["metadata"]["agno_event_type"] == "run_cancelled"
        assert final_status_events[0]["result"]["metadata"]["reason"] == "User requested cancellation"

        final_task = events[-1]
        assert final_task["result"]["kind"] == "task"
        assert final_task["result"]["status"]["state"] == "canceled"
        assert final_task["result"]["history"][0]["metadata"]["agno_event_type"] == "run_cancelled"

        parts = final_task["result"]["history"][0]["parts"]
        cancellation_text = " ".join([p["text"] for p in parts])
        assert "cancelled" in cancellation_text.lower()
        assert "User requested cancellation" in cancellation_text


def test_a2a_user_id_in_response_metadata(test_agent: Agent, test_client: TestClient):
    """Test that user_id is included in response message metadata when provided."""
    mock_output = RunOutput(
        run_id="test-run-123",
        session_id="context-789",
        agent_id=test_agent.id,
        agent_name=test_agent.name,
        content="Response",
        user_id="user-456",
    )

    with patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_output

        request_body = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "id": "request-123",
            "params": {
                "message": {
                    "messageId": "msg-123",
                    "role": "user",
                    "parts": [{"kind": "text", "text": "Hello!"}],
                }
            },
        }

        response = test_client.post(
            f"/a2a/agents/{test_agent.id}/v1/message:send", json=request_body, headers={"X-User-ID": "user-456"}
        )

        assert response.status_code == 200
        data = response.json()

        task = data["result"]
        assert len(task["history"]) == 1
        message = task["history"][0]
        assert message["metadata"] is not None
        assert message["metadata"]["userId"] == "user-456"


@pytest.fixture
def test_workflow():
    """Create a test workflow for A2A."""

    async def echo_step(input: str) -> str:
        return f"Workflow echo: {input}"

    workflow = Workflow(name="test-a2a-workflow", steps=[echo_step])
    return workflow


@pytest.fixture
def test_workflow_client(test_workflow: Workflow):
    """Create a FastAPI test client with A2A interface for workflows."""
    agent_os = AgentOS(workflows=[test_workflow], a2a_interface=True)
    app = agent_os.get_app()
    return TestClient(app)


def test_a2a_workflow(test_workflow: Workflow, test_workflow_client: TestClient):
    """Test the basic non-streaming A2A flow with a Workflow."""

    mock_output = WorkflowRunOutput(
        run_id="test-run-123",
        session_id="context-789",
        workflow_id=test_workflow.id,
        workflow_name=test_workflow.name,
        content="Workflow echo: Hello from workflow!",
        status=RunStatus.completed,
    )

    with patch.object(test_workflow, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_output

        request_body = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "id": "request-123",
            "params": {
                "message": {
                    "messageId": "msg-123",
                    "role": "user",
                    "contextId": "context-789",
                    "parts": [{"kind": "text", "text": "Hello, workflow!"}],
                }
            },
        }

        response = test_workflow_client.post(f"/a2a/workflows/{test_workflow.id}/v1/message:send", json=request_body)

        assert response.status_code == 200
        data = response.json()

        assert data["jsonrpc"] == "2.0"
        assert data["id"] == "request-123"
        assert "result" in data

        task = data["result"]
        assert task["contextId"] == "context-789"
        assert task["status"]["state"] == "completed"
        assert len(task["history"]) == 1

        message = task["history"][0]
        assert message["role"] == "agent"
        assert len(message["parts"]) == 1
        assert message["parts"][0]["kind"] == "text"
        assert message["parts"][0]["text"] == "Workflow echo: Hello from workflow!"

        mock_arun.assert_called_once()
        call_kwargs = mock_arun.call_args.kwargs
        assert call_kwargs["input"] == "Hello, workflow!"
        assert call_kwargs["session_id"] == "context-789"


def test_a2a_streaming_workflow(test_workflow: Workflow, test_workflow_client: TestClient):
    """Test the basic streaming A2A flow with a Workflow."""

    async def mock_event_stream():
        yield WorkflowStartedEvent(
            session_id="context-789",
            workflow_id=test_workflow.id,
            workflow_name=test_workflow.name,
            run_id="test-run-123",
        )

        yield WorkflowStepStartedEvent(
            session_id="context-789",
            workflow_id=test_workflow.id,
            workflow_name=test_workflow.name,
            run_id="test-run-123",
            step_name="echo_step",
        )

        yield WorkflowStepCompletedEvent(
            session_id="context-789",
            workflow_id=test_workflow.id,
            workflow_name=test_workflow.name,
            run_id="test-run-123",
            step_name="echo_step",
        )

        yield WorkflowCompletedEvent(
            session_id="context-789",
            workflow_id=test_workflow.id,
            workflow_name=test_workflow.name,
            run_id="test-run-123",
            content="Workflow echo: Hello from workflow!",
        )

    with patch.object(test_workflow, "arun") as mock_arun:
        mock_arun.return_value = mock_event_stream()

        request_body = {
            "jsonrpc": "2.0",
            "method": "message/stream",
            "id": "request-123",
            "params": {
                "message": {
                    "messageId": "msg-123",
                    "role": "user",
                    "contextId": "context-789",
                    "parts": [{"kind": "text", "text": "Hello, workflow!"}],
                }
            },
        }

        response = test_workflow_client.post(f"/a2a/workflows/{test_workflow.id}/v1/message:stream", json=request_body)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        # Parse SSE format: "event: EventType\ndata: JSON\n\n"
        events = []
        for chunk in response.text.split("\n\n"):
            if chunk.strip():
                lines = chunk.strip().split("\n")
                for line in lines:
                    if line.startswith("data: "):
                        events.append(json.loads(line[6:]))

        assert len(events) >= 2

        final_task = events[-1]
        assert final_task["result"]["kind"] == "task"
        assert final_task["result"]["status"]["state"] in ["completed", "failed"]
