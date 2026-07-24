import json
from typing import AsyncIterator, List
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


def parse_sse_events(response_text: str) -> List[dict]:
    """Parse SSE format ("event: EventType\\ndata: JSON\\n\\n") into JSON-RPC envelopes."""
    events = []
    for chunk in response_text.split("\n\n"):
        if chunk.strip():
            lines = chunk.strip().split("\n")
            for line in lines:
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
    return events


def get_status_updates(events: List[dict]) -> List[dict]:
    """Extract the StreamResponse `statusUpdate` payloads from JSON-RPC envelopes."""
    return [e["result"]["statusUpdate"] for e in events if "statusUpdate" in e["result"]]


def get_artifact_updates(events: List[dict]) -> List[dict]:
    """Extract the StreamResponse `artifactUpdate` payloads from JSON-RPC envelopes."""
    return [e["result"]["artifactUpdate"] for e in events if "artifactUpdate" in e["result"]]


def get_content_chunks(events: List[dict]) -> List[dict]:
    """Extract artifact updates carrying content chunks (parts-bearing artifacts)."""
    return [a for a in get_artifact_updates(events) if a.get("artifact", {}).get("parts")]


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
    assert "/a2a/agents/{id}/v1/message:send" in paths
    assert "/a2a/agents/{id}/v1/message:stream" in paths


def test_a2a_interface_in_interfaces_parameter():
    """Test that the A2A interface is setup correctly using the interfaces parameter."""
    interface_agent = Agent(name="interface-agent")
    os_agent = Agent(name="os-agent")
    agent_os = AgentOS(agents=[os_agent], interfaces=[A2A(agents=[interface_agent])])
    app = agent_os.get_app()

    assert app is not None
    assert any([isinstance(interface, A2A) for interface in agent_os.interfaces])
    paths = [route.path for route in agent_os.get_routes() if hasattr(route, "path")]
    assert "/a2a/agents/{id}/v1/message:send" in paths
    assert "/a2a/agents/{id}/v1/message:stream" in paths


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
                    "parts": [{"text": "Hello, agent!"}],
                }
            },
        }

        response = test_client.post(f"/a2a/agents/{test_agent.id}/v1/message:send", json=request_body)

        assert response.status_code == 200
        data = response.json()

        assert data["jsonrpc"] == "2.0"
        assert data["id"] == "request-123"
        assert "result" in data

        # v1: the Task is nested under result["task"] (SendMessageResponse oneof)
        task = data["result"]["task"]
        assert task["id"] == "test-run-123"
        assert task["contextId"] == "context-789"
        assert task["status"]["state"] == "TASK_STATE_COMPLETED"
        assert len(task["history"]) == 1

        message = task["history"][0]
        assert message["role"] == "ROLE_AGENT"
        assert len(message["parts"]) == 1
        assert message["parts"][0]["text"] == "Hello! This is a test response."
        assert message["parts"][0]["mediaType"] == "text/plain"

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
                    "parts": [{"text": "Hello, agent!"}],
                }
            },
        }

        response = test_client.post(f"/a2a/agents/{test_agent.id}/v1/message:stream", json=request_body)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        events = parse_sse_events(response.text)

        # Task (submitted), working, 3 content chunks, closing chunk, completed, final Task
        assert len(events) == 8
        for event in events:
            assert event["jsonrpc"] == "2.0"
            assert event["id"] == "request-123"

        # 1. The stream must open with the initial Task in submitted state
        initial_task = events[0]["result"]["task"]
        assert initial_task["id"] == "test-run-123"
        assert initial_task["contextId"] == "context-789"
        assert initial_task["status"]["state"] == "TASK_STATE_SUBMITTED"

        # 2. Working status update after the RunStartedEvent
        working_update = events[1]["result"]["statusUpdate"]
        assert working_update["status"]["state"] == "TASK_STATE_WORKING"
        assert working_update["taskId"] == "test-run-123"
        assert working_update["contextId"] == "context-789"

        # 3. Content chunks are streamed as artifact updates
        content_chunks = get_content_chunks(events)
        assert len(content_chunks) == 3
        assert content_chunks[0]["artifact"]["parts"][0]["text"] == "Hello! "
        assert content_chunks[1]["artifact"]["parts"][0]["text"] == "This is "
        assert content_chunks[2]["artifact"]["parts"][0]["text"] == "a streaming response."

        # First chunk creates the artifact (append omitted, i.e. false); later chunks append
        assert "append" not in content_chunks[0]
        assert content_chunks[1]["append"] is True
        assert content_chunks[2]["append"] is True

        artifact_ids = {chunk["artifact"]["artifactId"] for chunk in content_chunks}
        assert len(artifact_ids) == 1
        for chunk in content_chunks:
            assert chunk["artifact"]["name"] == "agent-response"
            assert chunk["metadata"]["agno_content_category"] == "content"
            assert chunk["taskId"] == "test-run-123"
            assert chunk["contextId"] == "context-789"

        # 4. The content artifact is closed with a last-chunk marker before completion
        closing_chunks = [a for a in get_artifact_updates(events) if a.get("lastChunk") is True]
        assert len(closing_chunks) == 1
        assert closing_chunks[0]["append"] is True
        assert closing_chunks[0]["artifact"]["artifactId"] in artifact_ids
        assert not closing_chunks[0]["artifact"].get("parts")

        # 5. Terminal status update: completed
        completed_updates = [s for s in get_status_updates(events) if s["status"]["state"] == "TASK_STATE_COMPLETED"]
        assert len(completed_updates) == 1

        # 6. The stream closes with the final Task snapshot
        final_task = events[-1]["result"]["task"]
        assert final_task["id"] == "test-run-123"
        assert final_task["contextId"] == "context-789"
        assert final_task["status"]["state"] == "TASK_STATE_COMPLETED"
        assert final_task["history"][0]["role"] == "ROLE_AGENT"
        assert final_task["history"][0]["parts"][0]["text"] == "Hello! this is a streaming response."

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
                    "parts": [{"text": "What's the weather in SF?"}],
                }
            },
        }

        response = test_client.post(f"/a2a/agents/{test_agent.id}/v1/message:stream", json=request_body)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        events = parse_sse_events(response.text)
        status_updates = get_status_updates(events)

        # Tool events surface as working status updates with agno metadata
        tool_started = [
            s for s in status_updates if s.get("metadata", {}).get("agno_event_type") == "tool_call_started"
        ]
        assert len(tool_started) == 1
        assert tool_started[0]["status"]["state"] == "TASK_STATE_WORKING"
        assert tool_started[0]["metadata"]["tool_name"] == "get_weather"
        tool_args = json.loads(tool_started[0]["metadata"]["tool_args"])
        assert tool_args == {"location": "Shanghai"}

        tool_completed = [
            s for s in status_updates if s.get("metadata", {}).get("agno_event_type") == "tool_call_completed"
        ]
        assert len(tool_completed) == 1
        assert tool_completed[0]["status"]["state"] == "TASK_STATE_WORKING"
        assert tool_completed[0]["metadata"]["tool_name"] == "get_weather"

        # Content is streamed as artifact updates
        content_chunks = get_content_chunks(events)
        assert len(content_chunks) == 1
        assert content_chunks[0]["artifact"]["parts"][0]["text"] == "The weather in Shanghai is 72°F and sunny."
        assert content_chunks[0]["metadata"]["agno_content_category"] == "content"

        final_task = events[-1]["result"]["task"]
        assert final_task["status"]["state"] == "TASK_STATE_COMPLETED"
        assert final_task["history"][0]["parts"][0]["text"] == "The weather in Shanghai is 72°F and sunny."


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
                    "parts": [{"text": "Help me think through this problem."}],
                }
            },
        }

        response = test_client.post(f"/a2a/agents/{test_agent.id}/v1/message:stream", json=request_body)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        events = parse_sse_events(response.text)
        status_updates = get_status_updates(events)

        reasoning_started = [
            s for s in status_updates if s.get("metadata", {}).get("agno_event_type") == "reasoning_started"
        ]
        assert len(reasoning_started) == 1
        assert reasoning_started[0]["status"]["state"] == "TASK_STATE_WORKING"

        # Reasoning steps surface as working status updates with the reasoning text
        # in metadata (a stream Message is terminal in v1, so they cannot be Messages)
        reasoning_steps = [
            s for s in status_updates if s.get("metadata", {}).get("agno_event_type") == "reasoning_step"
        ]
        assert len(reasoning_steps) == 2
        assert (
            reasoning_steps[0]["metadata"]["reasoning_content"]
            == "First, I need to understand what the user is asking..."
        )
        assert reasoning_steps[1]["metadata"]["reasoning_content"] == "Then I should formulate a clear response."

        for step in reasoning_steps:
            assert step["status"]["state"] == "TASK_STATE_WORKING"
            assert step["metadata"]["agno_content_category"] == "reasoning"
            assert step["metadata"]["step_type"] == "str"

        reasoning_completed = [
            s for s in status_updates if s.get("metadata", {}).get("agno_event_type") == "reasoning_completed"
        ]
        assert len(reasoning_completed) == 1

        content_chunks = get_content_chunks(events)
        assert len(content_chunks) == 1
        assert content_chunks[0]["artifact"]["parts"][0]["text"] == "Based on my analysis, here's the answer."
        assert content_chunks[0]["metadata"]["agno_content_category"] == "content"

        final_task = events[-1]["result"]["task"]
        assert final_task["status"]["state"] == "TASK_STATE_COMPLETED"
        assert final_task["history"][0]["parts"][0]["text"] == "Based on my analysis, here's the answer."


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
                    "parts": [{"text": "Remember this for later."}],
                }
            },
        }

        response = test_client.post(f"/a2a/agents/{test_agent.id}/v1/message:stream", json=request_body)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        events = parse_sse_events(response.text)
        status_updates = get_status_updates(events)

        memory_started = [
            s for s in status_updates if s.get("metadata", {}).get("agno_event_type") == "memory_update_started"
        ]
        assert len(memory_started) == 1
        assert memory_started[0]["status"]["state"] == "TASK_STATE_WORKING"

        memory_completed = [
            s for s in status_updates if s.get("metadata", {}).get("agno_event_type") == "memory_update_completed"
        ]
        assert len(memory_completed) == 1
        assert memory_completed[0]["status"]["state"] == "TASK_STATE_WORKING"

        content_chunks = get_content_chunks(events)
        assert len(content_chunks) == 1
        assert content_chunks[0]["artifact"]["parts"][0]["text"] == "I've updated my memory with this information."
        assert content_chunks[0]["metadata"]["agno_content_category"] == "content"

        final_task = events[-1]["result"]["task"]
        assert final_task["status"]["state"] == "TASK_STATE_COMPLETED"
        assert final_task["history"][0]["parts"][0]["text"] == "I've updated my memory with this information."


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
                    "parts": [{"text": "Hello, team!"}],
                }
            },
        }

        response = test_team_client.post(f"/a2a/teams/{test_team.id}/v1/message:send", json=request_body)

        assert response.status_code == 200
        data = response.json()

        assert data["jsonrpc"] == "2.0"
        assert data["id"] == "request-123"
        assert "result" in data

        task = data["result"]["task"]
        assert task["id"] == "test-run-123"
        assert task["contextId"] == "context-789"
        assert task["status"]["state"] == "TASK_STATE_COMPLETED"
        assert len(task["history"]) == 1

        message = task["history"][0]
        assert message["role"] == "ROLE_AGENT"
        assert len(message["parts"]) == 1
        assert message["parts"][0]["text"] == "Hello! This is a test response from the team."
        assert message["parts"][0]["mediaType"] == "text/plain"

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
                    "parts": [{"text": "Hello, team!"}],
                }
            },
        }

        response = test_team_client.post(f"/a2a/teams/{test_team.id}/v1/message:stream", json=request_body)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        events = parse_sse_events(response.text)

        # Task (submitted), working, 3 content chunks, closing chunk, completed, final Task
        assert len(events) == 8

        initial_task = events[0]["result"]["task"]
        assert initial_task["id"] == "test-run-123"
        assert initial_task["contextId"] == "context-789"
        assert initial_task["status"]["state"] == "TASK_STATE_SUBMITTED"

        working_update = events[1]["result"]["statusUpdate"]
        assert working_update["status"]["state"] == "TASK_STATE_WORKING"
        assert working_update["taskId"] == "test-run-123"
        assert working_update["contextId"] == "context-789"

        content_chunks = get_content_chunks(events)
        assert len(content_chunks) == 3
        assert content_chunks[0]["artifact"]["parts"][0]["text"] == "Hello! "
        assert content_chunks[1]["artifact"]["parts"][0]["text"] == "This is "
        assert content_chunks[2]["artifact"]["parts"][0]["text"] == "a streaming response from the team."

        for chunk in content_chunks:
            assert chunk["metadata"]["agno_content_category"] == "content"
            assert chunk["artifact"]["name"] == "agent-response"

        completed_updates = [s for s in get_status_updates(events) if s["status"]["state"] == "TASK_STATE_COMPLETED"]
        assert len(completed_updates) == 1

        final_task_event = events[-1]
        assert final_task_event["id"] == "request-123"
        final_task = final_task_event["result"]["task"]
        assert final_task["contextId"] == "context-789"
        assert final_task["status"]["state"] == "TASK_STATE_COMPLETED"
        assert final_task["history"][0]["parts"][0]["text"] == "Hello! this is a streaming response from the team."

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
                    "parts": [{"text": "Hello!"}],
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
                    "parts": [{"text": "Hello!"}],
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
                    "parts": [{"text": "Hello!"}],
                }
            },
        }

        response = test_client.post(f"/a2a/agents/{test_agent.id}/v1/message:send", json=request_body)

        assert response.status_code == 200
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert data["id"] == "request-123"

        task = data["result"]["task"]
        assert task["status"]["state"] == "TASK_STATE_FAILED"
        assert task["contextId"] == "context-789"
        assert len(task["history"]) == 1
        assert task["history"][0]["role"] == "ROLE_AGENT"
        # Exception details must NOT leak onto the wire — only a generic notice.
        wire_text = task["history"][0]["parts"][0]["text"]
        assert "Agent execution failed" not in wire_text
        assert "internal server error" in wire_text


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
                    "parts": [{"text": "Generate media"}],
                }
            },
        }

        response = test_client.post(f"/a2a/agents/{test_agent.id}/v1/message:stream", json=request_body)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        events = parse_sse_events(response.text)

        final_task = events[-1]["result"]["task"]
        assert final_task["status"]["state"] == "TASK_STATE_COMPLETED"

        artifacts = final_task.get("artifacts")
        assert artifacts is not None
        assert len(artifacts) == 3

        # v1 file parts carry the location in `url` (no nested `file` object)
        image_artifact = next((a for a in artifacts if "image" in a["artifactId"]), None)
        assert image_artifact is not None
        assert image_artifact["name"] == "image-0"
        assert image_artifact["parts"][0]["url"] == "https://example.com/image.png"
        assert image_artifact["parts"][0]["mediaType"] == "image/*"

        video_artifact = next((a for a in artifacts if "video" in a["artifactId"]), None)
        assert video_artifact is not None
        assert video_artifact["name"] == "video-0"
        assert video_artifact["parts"][0]["url"] == "https://example.com/video.mp4"
        assert video_artifact["parts"][0]["mediaType"] == "video/*"

        audio_artifact = next((a for a in artifacts if "audio" in a["artifactId"]), None)
        assert audio_artifact is not None
        assert audio_artifact["name"] == "audio-0"
        assert audio_artifact["parts"][0]["url"] == "https://example.com/audio.mp3"
        assert audio_artifact["parts"][0]["mediaType"] == "audio/*"


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
                    "parts": [{"text": "Start processing"}],
                }
            },
        }

        response = test_client.post(f"/a2a/agents/{test_agent.id}/v1/message:stream", json=request_body)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        events = parse_sse_events(response.text)

        content_chunks = get_content_chunks(events)
        assert len(content_chunks) == 1
        assert content_chunks[0]["artifact"]["parts"][0]["text"] == "Starting to process..."
        assert content_chunks[0]["metadata"]["agno_content_category"] == "content"

        # Cancelled runs do not emit a closing (last-chunk) artifact update
        closing_chunks = [a for a in get_artifact_updates(events) if a.get("lastChunk") is True]
        assert len(closing_chunks) == 0

        # Terminal status update: canceled, with cancellation metadata
        canceled_updates = [s for s in get_status_updates(events) if s["status"]["state"] == "TASK_STATE_CANCELED"]
        assert len(canceled_updates) == 1
        assert canceled_updates[0]["metadata"]["agno_event_type"] == "run_cancelled"
        assert canceled_updates[0]["metadata"]["reason"] == "User requested cancellation"

        final_task = events[-1]["result"]["task"]
        assert final_task["status"]["state"] == "TASK_STATE_CANCELED"
        assert final_task["history"][0]["metadata"]["agno_event_type"] == "run_cancelled"

        parts = final_task["history"][0]["parts"]
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
                    "parts": [{"text": "Hello!"}],
                }
            },
        }

        response = test_client.post(
            f"/a2a/agents/{test_agent.id}/v1/message:send", json=request_body, headers={"X-User-ID": "user-456"}
        )

        assert response.status_code == 200
        data = response.json()

        task = data["result"]["task"]
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
                    "parts": [{"text": "Hello, workflow!"}],
                }
            },
        }

        response = test_workflow_client.post(f"/a2a/workflows/{test_workflow.id}/v1/message:send", json=request_body)

        assert response.status_code == 200
        data = response.json()

        assert data["jsonrpc"] == "2.0"
        assert data["id"] == "request-123"
        assert "result" in data

        task = data["result"]["task"]
        assert task["contextId"] == "context-789"
        assert task["status"]["state"] == "TASK_STATE_COMPLETED"
        assert len(task["history"]) == 1

        message = task["history"][0]
        assert message["role"] == "ROLE_AGENT"
        assert len(message["parts"]) == 1
        assert message["parts"][0]["text"] == "Workflow echo: Hello from workflow!"
        assert message["parts"][0]["mediaType"] == "text/plain"

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
                    "parts": [{"text": "Hello, workflow!"}],
                }
            },
        }

        response = test_workflow_client.post(f"/a2a/workflows/{test_workflow.id}/v1/message:stream", json=request_body)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        events = parse_sse_events(response.text)

        assert len(events) >= 2

        # The stream opens with the initial Task in submitted state
        initial_task = events[0]["result"]["task"]
        assert initial_task["id"] == "test-run-123"
        assert initial_task["contextId"] == "context-789"
        assert initial_task["status"]["state"] == "TASK_STATE_SUBMITTED"

        status_updates = get_status_updates(events)

        working_updates = [s for s in status_updates if s["status"]["state"] == "TASK_STATE_WORKING"]
        assert len(working_updates) >= 1

        step_started = [
            s for s in status_updates if s.get("metadata", {}).get("agno_event_type") == "workflow_step_started"
        ]
        assert len(step_started) == 1
        assert step_started[0]["metadata"]["step_name"] == "echo_step"

        step_completed = [
            s for s in status_updates if s.get("metadata", {}).get("agno_event_type") == "workflow_step_completed"
        ]
        assert len(step_completed) == 1
        assert step_completed[0]["metadata"]["step_name"] == "echo_step"

        completed_updates = [s for s in status_updates if s["status"]["state"] == "TASK_STATE_COMPLETED"]
        assert len(completed_updates) == 1

        final_task = events[-1]["result"]["task"]
        assert final_task["contextId"] == "context-789"
        assert final_task["status"]["state"] == "TASK_STATE_COMPLETED"
        assert final_task["history"][0]["parts"][0]["text"] == "Workflow echo: Hello from workflow!"
