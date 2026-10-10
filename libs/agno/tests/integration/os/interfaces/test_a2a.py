import json
from typing import Any, AsyncIterator, Dict, List
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

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
    RunErrorEvent,
    RunOutput,
    RunOutputEvent,
    RunPausedEvent,
    RunStartedEvent,
    RunStatus,
    ToolCallCompletedEvent,
    ToolCallStartedEvent,
)
from agno.run.requirement import RunRequirement
from agno.run.workflow import (
    StepCompletedEvent as WorkflowStepCompletedEvent,
)
from agno.run.workflow import (
    StepStartedEvent as WorkflowStepStartedEvent,
)
from agno.run.workflow import (
    WorkflowCompletedEvent,
    WorkflowStartedEvent,
)
from agno.team import Team
from agno.workflow import Workflow


def _message_body(method: str, text: str, **message_fields: Any) -> Dict[str, Any]:
    """An A2A v0.3 JSON-RPC request, as sent by clients built before A2A v1.0."""
    return {
        "jsonrpc": "2.0",
        "method": method,
        "id": "request-123",
        "params": {
            "message": {
                "messageId": "msg-123",
                "role": "user",
                "contextId": "context-789",
                "parts": [{"kind": "text", "text": text}],
                **message_fields,
            }
        },
    }


def _parse_sse_events(raw: str) -> List[Dict[str, Any]]:
    """Parse the "data: {...}" lines of an SSE response."""
    return [json.loads(line[len("data: ") :]) for line in raw.splitlines() if line.startswith("data: ")]


def _response_text(task: Dict[str, Any]) -> str:
    """The text of the response artifact of an A2A task."""
    response_artifacts = [artifact for artifact in task.get("artifacts", []) if artifact.get("name") == "response"]
    assert len(response_artifacts) == 1
    return "".join(part.get("text", "") for part in response_artifacts[0]["parts"])


@pytest.fixture
def test_agent():
    """Create a test agent for A2A."""
    agent = Agent(name="test-a2a-agent", instructions="You are a helpful assistant.")
    # Return same instance from deep_copy so arun patches work
    agent.deep_copy = lambda **kwargs: agent
    return agent


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
    paths = [route.path for route in agent_os.get_routes() if hasattr(route, "path")]
    assert "/a2a/agents/{id}/.well-known/agent-card.json" in paths
    assert f"/a2a/agents/{agent.id}" in paths


def test_a2a_interface_in_interfaces_parameter():
    """Test that the A2A interface is setup correctly using the interfaces parameter."""
    interface_agent = Agent(name="interface-agent")
    os_agent = Agent(name="os-agent")
    agent_os = AgentOS(agents=[os_agent], interfaces=[A2A(agents=[interface_agent])])
    app = agent_os.get_app()

    assert app is not None
    assert any([isinstance(interface, A2A) for interface in agent_os.interfaces])
    paths = [route.path for route in agent_os.get_routes() if hasattr(route, "path")]
    assert "/a2a/agents/{id}/.well-known/agent-card.json" in paths
    assert f"/a2a/agents/{interface_agent.id}" in paths


def test_a2a_agent_card(test_agent: Agent, test_client: TestClient):
    """Test the Agent Card describes the agent and the endpoint it is served on."""
    response = test_client.get(f"/a2a/agents/{test_agent.id}/.well-known/agent-card.json")

    assert response.status_code == 200
    card = response.json()

    assert card["name"] == "test-a2a-agent"
    assert card["capabilities"]["streaming"] is True
    assert card["skills"][0]["id"] == test_agent.id
    assert "examples" not in card["skills"][0]

    endpoint = f"http://testserver/a2a/agents/{test_agent.id}"
    assert card["supportedInterfaces"] == [
        {"url": endpoint, "protocolBinding": "JSONRPC", "protocolVersion": "1.0"},
        {"url": endpoint, "protocolBinding": "JSONRPC", "protocolVersion": "0.3"},
    ]
    # The fields A2A v0.3 clients read
    assert card["url"] == endpoint
    assert card["preferredTransport"] == "JSONRPC"


def test_a2a(test_agent: Agent, test_client: TestClient):
    """Test the basic non-streaming A2A flow."""

    async def mock_event_stream() -> AsyncIterator[RunOutputEvent]:
        yield RunStartedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
        )

        yield RunCompletedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
            content="Hello! This is a test response.",
        )

    with patch.object(test_agent, "arun") as mock_arun:
        mock_arun.return_value = mock_event_stream()

        request_body = _message_body("message/send", "Hello, agent!")

        response = test_client.post(f"/a2a/agents/{test_agent.id}", json=request_body)

        assert response.status_code == 200
        data = response.json()

        assert data["jsonrpc"] == "2.0"
        assert data["id"] == "request-123"
        assert "result" in data

        task = data["result"]
        assert task["kind"] == "task"
        assert task["contextId"] == "context-789"
        assert task["status"]["state"] == "completed"
        assert _response_text(task) == "Hello! This is a test response."

        # The user message is kept in the task history
        assert len(task["history"]) == 1
        assert task["history"][0]["role"] == "user"

        mock_arun.assert_called_once()
        call_kwargs = mock_arun.call_args.kwargs
        assert call_kwargs["input"] == "Hello, agent!"
        assert call_kwargs["session_id"] == "context-789"
        # The task shares its id with the run
        assert call_kwargs["run_id"] == task["id"]


def test_a2a_v1(test_agent: Agent, test_client: TestClient):
    """Test the basic non-streaming flow with the A2A v1.0 method and wire format."""

    async def mock_event_stream() -> AsyncIterator[RunOutputEvent]:
        yield RunStartedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
        )

        yield RunCompletedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
            content="Hello! This is a test response.",
        )

    with patch.object(test_agent, "arun") as mock_arun:
        mock_arun.return_value = mock_event_stream()

        request_body = {
            "jsonrpc": "2.0",
            "method": "SendMessage",
            "id": "request-123",
            "params": {
                "message": {
                    "messageId": "msg-123",
                    "role": "ROLE_USER",
                    "contextId": "context-789",
                    "parts": [{"text": "Hello, agent!"}],
                }
            },
        }

        response = test_client.post(f"/a2a/agents/{test_agent.id}", json=request_body, headers={"A2A-Version": "1.0"})

        assert response.status_code == 200
        task = response.json()["result"]["task"]
        assert task["contextId"] == "context-789"
        assert task["status"]["state"] == "TASK_STATE_COMPLETED"
        assert _response_text(task) == "Hello! This is a test response."

        # The task can be read back by its id
        response = test_client.post(
            f"/a2a/agents/{test_agent.id}",
            json={"jsonrpc": "2.0", "method": "GetTask", "id": "request-124", "params": {"id": task["id"]}},
            headers={"A2A-Version": "1.0"},
        )

        assert response.status_code == 200
        assert response.json()["result"]["status"]["state"] == "TASK_STATE_COMPLETED"


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

        request_body = _message_body("message/stream", "Hello, agent!")

        response = test_client.post(f"/a2a/agents/{test_agent.id}", json=request_body)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        events = _parse_sse_events(response.text)

        assert len(events) >= 5

        # The stream opens with the task, then reports it working
        assert events[0]["result"]["kind"] == "task"
        assert events[0]["result"]["contextId"] == "context-789"
        task_id = events[0]["result"]["id"]

        assert events[1]["result"]["kind"] == "status-update"
        assert events[1]["result"]["status"]["state"] == "working"
        assert events[1]["result"]["taskId"] == task_id
        assert events[1]["result"]["contextId"] == "context-789"

        content_chunks = [
            e for e in events if e["result"].get("kind") == "artifact-update" and not e["result"].get("lastChunk")
        ]
        assert len(content_chunks) == 3
        assert content_chunks[0]["result"]["artifact"]["parts"][0]["text"] == "Hello! "
        assert content_chunks[1]["result"]["artifact"]["parts"][0]["text"] == "This is "
        assert content_chunks[2]["result"]["artifact"]["parts"][0]["text"] == "a streaming response."

        for chunk in content_chunks:
            assert chunk["result"]["artifact"]["metadata"]["agno_content_category"] == "content"
            assert chunk["result"]["artifact"]["name"] == "response"

        # The complete response closes the artifact
        final_chunks = [
            e for e in events if e["result"].get("kind") == "artifact-update" and e["result"].get("lastChunk")
        ]
        assert len(final_chunks) == 1
        assert final_chunks[0]["result"]["artifact"]["parts"][0]["text"] == "Hello! this is a streaming response."

        final_status_events = [
            e for e in events if e["result"].get("kind") == "status-update" and e["result"].get("final") is True
        ]
        assert len(final_status_events) == 1
        assert final_status_events[0]["result"]["status"]["state"] == "completed"
        assert events[-1] == final_status_events[0]

        mock_arun.assert_called_once()
        call_kwargs = mock_arun.call_args.kwargs
        assert call_kwargs["input"] == "Hello, agent!"
        assert call_kwargs["session_id"] == "context-789"
        assert call_kwargs["run_id"] == task_id
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

        request_body = _message_body("message/stream", "What's the weather in Shanghai?")

        response = test_client.post(f"/a2a/agents/{test_agent.id}", json=request_body)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        events = _parse_sse_events(response.text)

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

        content_chunks = [e for e in events if e["result"].get("kind") == "artifact-update"]
        assert (
            content_chunks[0]["result"]["artifact"]["parts"][0]["text"] == "The weather in Shanghai is 72°F and sunny."
        )
        assert content_chunks[0]["result"]["artifact"]["metadata"]["agno_content_category"] == "content"

        final_status = events[-1]
        assert final_status["result"]["kind"] == "status-update"
        assert final_status["result"]["status"]["state"] == "completed"
        assert final_status["result"]["final"] is True


def test_a2a_streaming_with_reasoning(test_agent: Agent, test_client: TestClient):
    """Test A2A streaming flow with reasoning events."""

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

        request_body = _message_body("message/stream", "Help me think through this problem.")

        response = test_client.post(f"/a2a/agents/{test_agent.id}", json=request_body)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        events = _parse_sse_events(response.text)

        reasoning_started = [
            e for e in events if e["result"].get("metadata", {}).get("agno_event_type") == "reasoning_started"
        ]
        assert len(reasoning_started) == 1
        assert reasoning_started[0]["result"]["kind"] == "status-update"
        assert reasoning_started[0]["result"]["status"]["state"] == "working"

        # Reasoning streams as its own artifact, apart from the response
        reasoning_chunks = [
            e
            for e in events
            if e["result"].get("kind") == "artifact-update"
            and e["result"]["artifact"].get("metadata", {}).get("agno_content_category") == "reasoning"
        ]
        assert len(reasoning_chunks) == 2
        assert (
            reasoning_chunks[0]["result"]["artifact"]["parts"][0]["text"]
            == "First, I need to understand what the user is asking..."
        )
        assert (
            reasoning_chunks[1]["result"]["artifact"]["parts"][0]["text"] == "Then I should formulate a clear response."
        )

        for chunk in reasoning_chunks:
            assert chunk["result"]["artifact"]["name"] == "reasoning"
            assert chunk["result"]["artifact"]["metadata"]["agno_event_type"] == "reasoning_step"

        reasoning_completed = [
            e for e in events if e["result"].get("metadata", {}).get("agno_event_type") == "reasoning_completed"
        ]
        assert len(reasoning_completed) == 1
        assert reasoning_completed[0]["result"]["kind"] == "status-update"

        content_chunks = [
            e
            for e in events
            if e["result"].get("kind") == "artifact-update"
            and e["result"]["artifact"].get("metadata", {}).get("agno_content_category") == "content"
        ]
        assert content_chunks[0]["result"]["artifact"]["parts"][0]["text"] == "Based on my analysis, here's the answer."

        final_status = events[-1]
        assert final_status["result"]["kind"] == "status-update"
        assert final_status["result"]["status"]["state"] == "completed"


def test_a2a_streaming_with_memory(test_agent: Agent, test_client: TestClient):
    """Test A2A streaming flow with memory update events."""

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
            content="I've updated my memory with this information.",
        )

    with patch.object(test_agent, "arun") as mock_arun:
        mock_arun.return_value = mock_event_stream()

        request_body = _message_body("message/stream", "Remember that I like Python.")

        response = test_client.post(f"/a2a/agents/{test_agent.id}", json=request_body)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        events = _parse_sse_events(response.text)

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

        content_chunks = [e for e in events if e["result"].get("kind") == "artifact-update"]
        assert (
            content_chunks[0]["result"]["artifact"]["parts"][0]["text"]
            == "I've updated my memory with this information."
        )

        final_status = events[-1]
        assert final_status["result"]["kind"] == "status-update"
        assert final_status["result"]["status"]["state"] == "completed"


@pytest.fixture
def test_team():
    """Create a test team for A2A."""
    agent1 = Agent(name="agent1", instructions="You are agent 1.")
    agent2 = Agent(name="agent2", instructions="You are agent 2.")
    team = Team(name="test-a2a-team", members=[agent1, agent2], instructions="You are a helpful team.")
    # Return same instance from deep_copy so arun patches work
    team.deep_copy = lambda **kwargs: team
    return team


@pytest.fixture
def test_team_client(test_team: Team):
    """Create a FastAPI test client with A2A interface for teams."""
    agent_os = AgentOS(teams=[test_team], a2a_interface=True)
    app = agent_os.get_app()
    return TestClient(app)


def test_a2a_team(test_team: Team, test_team_client: TestClient):
    """Test the basic non-streaming A2A flow with a Team."""

    async def mock_event_stream() -> AsyncIterator[RunOutputEvent]:
        yield RunStartedEvent(
            session_id="context-789",
            agent_id=test_team.id,
            agent_name=test_team.name,
            run_id="test-run-123",
        )

        yield RunCompletedEvent(
            session_id="context-789",
            agent_id=test_team.id,
            agent_name=test_team.name,
            run_id="test-run-123",
            content="Hello! This is a test response from the team.",
        )

    with patch.object(test_team, "arun") as mock_arun:
        mock_arun.return_value = mock_event_stream()

        request_body = _message_body("message/send", "Hello, team!")

        response = test_team_client.post(f"/a2a/teams/{test_team.id}", json=request_body)

        assert response.status_code == 200
        data = response.json()

        assert data["jsonrpc"] == "2.0"
        assert data["id"] == "request-123"
        assert "result" in data

        task = data["result"]
        assert task["contextId"] == "context-789"
        assert task["status"]["state"] == "completed"
        assert _response_text(task) == "Hello! This is a test response from the team."

        mock_arun.assert_called_once()
        call_kwargs = mock_arun.call_args.kwargs
        assert call_kwargs["input"] == "Hello, team!"
        assert call_kwargs["session_id"] == "context-789"
        assert call_kwargs["run_id"] == task["id"]


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
            content="Hello! This is a streaming response from the team.",
        )

    with patch.object(test_team, "arun") as mock_arun:
        mock_arun.return_value = mock_event_stream()

        request_body = _message_body("message/stream", "Hello, team!")

        response = test_team_client.post(f"/a2a/teams/{test_team.id}", json=request_body)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        events = _parse_sse_events(response.text)

        assert len(events) >= 5

        assert events[0]["result"]["kind"] == "task"
        assert events[0]["result"]["contextId"] == "context-789"
        assert events[1]["result"]["kind"] == "status-update"
        assert events[1]["result"]["status"]["state"] == "working"

        content_chunks = [
            e for e in events if e["result"].get("kind") == "artifact-update" and not e["result"].get("lastChunk")
        ]
        assert len(content_chunks) == 3
        assert content_chunks[0]["result"]["artifact"]["parts"][0]["text"] == "Hello! "
        assert content_chunks[1]["result"]["artifact"]["parts"][0]["text"] == "This is "
        assert content_chunks[2]["result"]["artifact"]["parts"][0]["text"] == "a streaming response from the team."

        for chunk in content_chunks:
            assert chunk["result"]["artifact"]["metadata"]["agno_content_category"] == "content"

        final_status_events = [
            e for e in events if e["result"].get("kind") == "status-update" and e["result"].get("final") is True
        ]
        assert len(final_status_events) == 1
        assert final_status_events[0]["result"]["status"]["state"] == "completed"

        mock_arun.assert_called_once()
        call_kwargs = mock_arun.call_args.kwargs
        assert call_kwargs["input"] == "Hello, team!"
        assert call_kwargs["session_id"] == "context-789"
        assert call_kwargs["stream"] is True
        assert call_kwargs["stream_events"] is True


def test_a2a_user_id_from_header(test_agent: Agent, test_client: TestClient):
    """Test that user_id is extracted from X-User-ID header and passed to arun."""

    async def mock_event_stream() -> AsyncIterator[RunOutputEvent]:
        yield RunCompletedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
            content="Response",
        )

    with patch.object(test_agent, "arun") as mock_arun:
        mock_arun.return_value = mock_event_stream()

        request_body = _message_body("message/send", "Hello!")

        response = test_client.post(
            f"/a2a/agents/{test_agent.id}", json=request_body, headers={"X-User-ID": "user-456"}
        )

        assert response.status_code == 200
        mock_arun.assert_called_once()
        call_kwargs = mock_arun.call_args.kwargs
        assert call_kwargs["user_id"] == "user-456"


def test_a2a_user_id_from_metadata(test_agent: Agent, test_client: TestClient):
    """Test that user_id is extracted from params.message.metadata as fallback."""

    async def mock_event_stream() -> AsyncIterator[RunOutputEvent]:
        yield RunCompletedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
            content="Response",
        )

    with patch.object(test_agent, "arun") as mock_arun:
        mock_arun.return_value = mock_event_stream()

        request_body = _message_body("message/send", "Hello!", metadata={"userId": "user-789"})

        response = test_client.post(f"/a2a/agents/{test_agent.id}", json=request_body)

        assert response.status_code == 200
        mock_arun.assert_called_once()
        call_kwargs = mock_arun.call_args.kwargs
        assert call_kwargs["user_id"] == "user-789"


def test_a2a_error_handling_non_streaming(test_agent: Agent, test_client: TestClient):
    """Test that errors during agent execution return a failed Task."""

    with patch.object(test_agent, "arun") as mock_arun:
        mock_arun.side_effect = Exception("Agent execution failed")

        request_body = _message_body("message/send", "Hello!")

        response = test_client.post(f"/a2a/agents/{test_agent.id}", json=request_body)

        assert response.status_code == 200
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == "request-123"
        assert data["result"]["status"]["state"] == "failed"
        assert data["result"]["contextId"] == "context-789"
        assert "Agent execution failed" in data["result"]["status"]["message"]["parts"][0]["text"]


def test_a2a_error_event_non_streaming(test_agent: Agent, test_client: TestClient):
    """Test that a run ending with an error event returns a failed Task with the error."""

    async def mock_event_stream() -> AsyncIterator[RunOutputEvent]:
        yield RunStartedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
        )

        yield RunErrorEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
            content="The model is unavailable",
        )

    with patch.object(test_agent, "arun") as mock_arun:
        mock_arun.return_value = mock_event_stream()

        request_body = _message_body("message/send", "Hello!")

        response = test_client.post(f"/a2a/agents/{test_agent.id}", json=request_body)

        assert response.status_code == 200
        data = response.json()
        assert data["result"]["status"]["state"] == "failed"
        assert data["result"]["status"]["message"]["parts"][0]["text"] == "The model is unavailable"


def test_a2a_structured_output(test_agent: Agent, test_client: TestClient):
    """Test that structured output is returned as a data part, not as text."""

    class City(BaseModel):
        city: str
        country: str

    async def mock_event_stream() -> AsyncIterator[RunOutputEvent]:
        yield RunCompletedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
            content=City(city="Paris", country="France"),
        )

    with patch.object(test_agent, "arun") as mock_arun:
        mock_arun.return_value = mock_event_stream()

        request_body = _message_body("message/send", "Where is the Eiffel Tower?")

        response = test_client.post(f"/a2a/agents/{test_agent.id}", json=request_body)

        assert response.status_code == 200
        task = response.json()["result"]
        assert task["artifacts"][0]["parts"][0]["kind"] == "data"
        assert task["artifacts"][0]["parts"][0]["data"] == {"city": "Paris", "country": "France"}


def test_a2a_paused_run(test_agent: Agent, test_client: TestClient):
    """Test that a paused run waits for input, and is continued by a message naming its task."""

    requirement = RunRequirement(
        tool_execution=ToolExecution(tool_call_id="call-1", tool_name="refund", requires_confirmation=True)
    )

    async def mock_event_stream() -> AsyncIterator[RunOutputEvent]:
        yield RunStartedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
        )

        yield RunPausedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
            requirements=[requirement],
        )

    with patch.object(test_agent, "arun") as mock_arun:
        mock_arun.return_value = mock_event_stream()

        response = test_client.post(
            f"/a2a/agents/{test_agent.id}", json=_message_body("message/send", "Refund order 42.")
        )

        assert response.status_code == 200
        task = response.json()["result"]
        assert task["status"]["state"] == "input-required"

        # The requirements the run waits on come with the task
        data_parts = [part["data"] for part in task["status"]["message"]["parts"] if part["kind"] == "data"]
        assert data_parts[0]["requirements"][0]["id"] == requirement.id

    # The client resolves the requirements and sends them back to the same task
    requirements = data_parts[0]["requirements"]
    requirements[0]["confirmation"] = True
    continued_output = RunOutput(
        run_id=task["id"], session_id="context-789", content="Order 42 refunded.", status=RunStatus.completed
    )

    with patch("agno.os.services.runs.continue_paused_run", new_callable=AsyncMock) as mock_continue:
        mock_continue.return_value = continued_output

        request_body = _message_body("message/send", "", taskId=task["id"])
        request_body["params"]["message"]["parts"] = [{"kind": "data", "data": {"requirements": requirements}}]

        response = test_client.post(f"/a2a/agents/{test_agent.id}", json=request_body)

        assert response.status_code == 200
        continued_task = response.json()["result"]
        assert continued_task["id"] == task["id"]
        assert continued_task["status"]["state"] == "completed"
        assert _response_text(continued_task) == "Order 42 refunded."

        call_kwargs = mock_continue.call_args.kwargs
        assert call_kwargs["run_id"] == task["id"]
        assert call_kwargs["requirements"][0]["confirmation"] is True


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

        request_body = _message_body("message/stream", "Generate an image")

        response = test_client.post(f"/a2a/agents/{test_agent.id}", json=request_body)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        events = _parse_sse_events(response.text)

        final_status = events[-1]
        assert final_status["result"]["kind"] == "status-update"
        assert final_status["result"]["status"]["state"] == "completed"

        artifacts = {
            e["result"]["artifact"]["artifactId"]: e["result"]["artifact"]
            for e in events
            if e["result"].get("kind") == "artifact-update"
        }

        image_artifact = artifacts.get("image-0")
        assert image_artifact is not None
        assert image_artifact["name"] == "image-0"
        assert image_artifact["parts"][0]["file"]["uri"] == "https://example.com/image.png"

        video_artifact = artifacts.get("video-0")
        assert video_artifact is not None
        assert video_artifact["name"] == "video-0"
        assert video_artifact["parts"][0]["file"]["uri"] == "https://example.com/video.mp4"

        audio_artifact = artifacts.get("audio-0")
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

        request_body = _message_body("message/stream", "Start processing")

        response = test_client.post(f"/a2a/agents/{test_agent.id}", json=request_body)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        events = _parse_sse_events(response.text)

        content_chunks = [
            e
            for e in events
            if e["result"].get("kind") == "artifact-update"
            and e["result"]["artifact"].get("metadata", {}).get("agno_content_category") == "content"
        ]
        assert content_chunks[0]["result"]["artifact"]["parts"][0]["text"] == "Starting to process..."

        final_status_events = [
            e for e in events if e["result"].get("kind") == "status-update" and e["result"].get("final") is True
        ]
        assert len(final_status_events) == 1
        assert final_status_events[0]["result"]["status"]["state"] == "canceled"
        assert final_status_events[0]["result"]["metadata"]["agno_event_type"] == "run_cancelled"
        assert final_status_events[0]["result"]["metadata"]["reason"] == "User requested cancellation"

        cancellation_text = final_status_events[0]["result"]["status"]["message"]["parts"][0]["text"]
        assert "cancelled" in cancellation_text.lower()
        assert "User requested cancellation" in cancellation_text


def test_a2a_user_id_in_response_metadata(test_agent: Agent, test_client: TestClient):
    """Test that user_id is included in response task metadata when provided."""

    async def mock_event_stream() -> AsyncIterator[RunOutputEvent]:
        yield RunCompletedEvent(
            session_id="context-789",
            agent_id=test_agent.id,
            agent_name=test_agent.name,
            run_id="test-run-123",
            content="Response",
        )

    with patch.object(test_agent, "arun") as mock_arun:
        mock_arun.return_value = mock_event_stream()

        request_body = _message_body("message/send", "Hello!")

        response = test_client.post(
            f"/a2a/agents/{test_agent.id}", json=request_body, headers={"X-User-ID": "user-456"}
        )

        assert response.status_code == 200
        data = response.json()

        task = data["result"]
        assert task["metadata"] is not None
        assert task["metadata"]["userId"] == "user-456"


@pytest.fixture
def test_workflow():
    """Create a test workflow for A2A."""

    async def echo_step(input: str) -> str:
        return f"Workflow echo: {input}"

    workflow = Workflow(name="test-a2a-workflow", steps=[echo_step])
    # Return same instance from deep_copy so arun patches work
    workflow.deep_copy = lambda **kwargs: workflow
    return workflow


@pytest.fixture
def test_workflow_client(test_workflow: Workflow):
    """Create a FastAPI test client with A2A interface for workflows."""
    agent_os = AgentOS(workflows=[test_workflow], a2a_interface=True)
    app = agent_os.get_app()
    return TestClient(app)


def test_a2a_workflow(test_workflow: Workflow, test_workflow_client: TestClient):
    """Test the basic non-streaming A2A flow with a Workflow."""

    async def mock_event_stream():
        yield WorkflowStartedEvent(
            session_id="context-789",
            workflow_id=test_workflow.id,
            workflow_name=test_workflow.name,
            run_id="test-run-123",
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

        request_body = _message_body("message/send", "Hello, workflow!")

        response = test_workflow_client.post(f"/a2a/workflows/{test_workflow.id}", json=request_body)

        assert response.status_code == 200
        data = response.json()

        assert data["jsonrpc"] == "2.0"
        assert data["id"] == "request-123"
        assert "result" in data

        task = data["result"]
        assert task["contextId"] == "context-789"
        assert task["status"]["state"] == "completed"
        assert _response_text(task) == "Workflow echo: Hello from workflow!"

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

        request_body = _message_body("message/stream", "Hello, workflow!")

        response = test_workflow_client.post(f"/a2a/workflows/{test_workflow.id}", json=request_body)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        events = _parse_sse_events(response.text)

        assert len(events) >= 2

        step_started = [
            e for e in events if e["result"].get("metadata", {}).get("agno_event_type") == "workflow_step_started"
        ]
        assert len(step_started) == 1
        assert step_started[0]["result"]["metadata"]["step_name"] == "echo_step"

        final_status = events[-1]
        assert final_status["result"]["kind"] == "status-update"
        assert final_status["result"]["status"]["state"] == "completed"
