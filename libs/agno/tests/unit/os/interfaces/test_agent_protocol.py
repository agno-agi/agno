"""Unit tests for the Agent Protocol interface.

Tests verify:
- Interface setup via flag and explicit parameter
- Endpoint registration
- Thread CRUD
- Background runs (thread-scoped)
- Agent introspection
- Stateless runs with mocked agent execution
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.os.app import AgentOS
from agno.os.interfaces.agent_protocol import AgentProtocol
from agno.run.agent import RunOutput
from agno.run.base import RunStatus


@pytest.fixture
def test_agent():
    """Create a test agent for Agent Protocol."""
    return Agent(
        name="test-ap-agent",
        id="test_ap_agent",
        description="A test agent for Agent Protocol",
        instructions="You are a helpful assistant.",
    )


@pytest.fixture
def test_client(test_agent: Agent):
    """Create a FastAPI test client with Agent Protocol interface."""
    agent_os = AgentOS(agents=[test_agent], agent_protocol_interface=True)
    app = agent_os.get_app()
    return TestClient(app)


# ============================================================================
# Interface Setup Tests
# ============================================================================


def test_agent_protocol_interface_parameter():
    """Test that the Agent Protocol interface is setup correctly using the flag."""
    agent = Agent()
    agent_os = AgentOS(agents=[agent], agent_protocol_interface=True)
    app = agent_os.get_app()

    assert app is not None
    assert any(isinstance(interface, AgentProtocol) for interface in agent_os.interfaces)
    # Check that key routes are registered
    route_paths = [route.path for route in app.routes]  # type: ignore
    assert "/ap/threads" in route_paths
    assert "/ap/threads/{thread_id}" in route_paths
    assert "/ap/threads/{thread_id}/runs" in route_paths
    assert "/ap/threads/{thread_id}/runs/{run_id}" in route_paths
    assert "/ap/agents/search" in route_paths
    assert "/ap/runs/wait" in route_paths
    assert "/ap/runs/stream" in route_paths
    assert "/ap/store/items" in route_paths


def test_agent_protocol_interface_in_interfaces_parameter():
    """Test that the Agent Protocol interface is setup correctly using the interfaces parameter."""
    interface_agent = Agent(name="interface-agent", id="interface_agent")
    os_agent = Agent(name="os-agent")
    agent_os = AgentOS(agents=[os_agent], interfaces=[AgentProtocol(agents=[interface_agent])])
    app = agent_os.get_app()

    assert app is not None
    assert any(isinstance(interface, AgentProtocol) for interface in agent_os.interfaces)
    route_paths = [route.path for route in app.routes]  # type: ignore
    assert "/ap/threads" in route_paths
    assert "/ap/agents/search" in route_paths


def test_agent_protocol_custom_prefix():
    """Test that the Agent Protocol interface supports custom prefixes."""
    agent = Agent()
    agent_os = AgentOS(agents=[agent], interfaces=[AgentProtocol(agents=[agent], prefix="/custom")])
    app = agent_os.get_app()

    route_paths = [route.path for route in app.routes]  # type: ignore
    assert "/custom/threads" in route_paths
    assert "/custom/agents/search" in route_paths


def test_agent_protocol_requires_agents():
    """Test that the Agent Protocol interface requires agents, teams, or workflows."""
    with pytest.raises(ValueError, match="Agents, Teams, or Workflows are required"):
        AgentProtocol()


# ============================================================================
# Thread Tests
# ============================================================================


def test_create_thread(test_client: TestClient):
    """Test creating a new thread."""
    response = test_client.post("/ap/threads", json={})
    assert response.status_code == 200
    data = response.json()
    assert "thread_id" in data
    assert data["status"] == "idle"
    assert data["values"] == {}
    assert "created_at" in data
    assert "updated_at" in data


def test_get_thread(test_client: TestClient):
    """Test getting a thread by ID."""
    # Create a thread first
    create_resp = test_client.post("/ap/threads", json={})
    thread_id = create_resp.json()["thread_id"]

    # Get it
    response = test_client.get(f"/ap/threads/{thread_id}")
    assert response.status_code == 200
    assert response.json()["thread_id"] == thread_id


def test_get_thread_not_found(test_client: TestClient):
    """Test getting a non-existent thread returns 404."""
    response = test_client.get("/ap/threads/nonexistent")
    assert response.status_code == 404


def test_delete_thread(test_client: TestClient):
    """Test deleting a thread."""
    create_resp = test_client.post("/ap/threads", json={})
    thread_id = create_resp.json()["thread_id"]

    response = test_client.delete(f"/ap/threads/{thread_id}")
    assert response.status_code == 200

    # Verify deleted
    response = test_client.get(f"/ap/threads/{thread_id}")
    assert response.status_code == 404


def test_update_thread(test_client: TestClient):
    """Test updating a thread's metadata."""
    create_resp = test_client.post("/ap/threads", json={})
    thread_id = create_resp.json()["thread_id"]

    response = test_client.patch(f"/ap/threads/{thread_id}", json={"metadata": {"key": "value"}})
    assert response.status_code == 200
    assert response.json()["metadata"]["key"] == "value"


def test_search_threads(test_client: TestClient):
    """Test searching threads."""
    # Create some threads
    test_client.post("/ap/threads", json={"metadata": {"env": "test"}})
    test_client.post("/ap/threads", json={"metadata": {"env": "prod"}})

    response = test_client.post("/ap/threads/search", json={})
    assert response.status_code == 200
    assert len(response.json()) >= 2


def test_copy_thread(test_client: TestClient):
    """Test copying a thread."""
    create_resp = test_client.post("/ap/threads", json={"metadata": {"source": "original"}})
    thread_id = create_resp.json()["thread_id"]

    response = test_client.post(f"/ap/threads/{thread_id}/copy")
    assert response.status_code == 200
    copy_data = response.json()
    assert copy_data["thread_id"] != thread_id
    assert copy_data["metadata"]["source"] == "original"


# ============================================================================
# Agent Introspection Tests
# ============================================================================


def test_search_agents(test_client: TestClient, test_agent: Agent):
    """Test listing registered agents."""
    response = test_client.post("/ap/agents/search", json={})
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    agent_ids = [a["agent_id"] for a in data]
    assert test_agent.id in agent_ids


def test_get_agent(test_client: TestClient, test_agent: Agent):
    """Test getting an agent by ID."""
    response = test_client.get(f"/ap/agents/{test_agent.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["agent_id"] == test_agent.id
    assert data["name"] == test_agent.name
    assert data["capabilities"]["ap.io.messages"] is True


def test_get_agent_not_found(test_client: TestClient):
    """Test getting a non-existent agent returns 404."""
    response = test_client.get("/ap/agents/nonexistent")
    assert response.status_code == 404


def test_get_agent_schemas(test_client: TestClient, test_agent: Agent):
    """Test getting agent schemas."""
    response = test_client.get(f"/ap/agents/{test_agent.id}/schemas")
    assert response.status_code == 200
    data = response.json()
    assert data["agent_id"] == test_agent.id
    assert "input_schema" in data
    assert "output_schema" in data


# ============================================================================
# Background Run Tests (Thread-Scoped)
# ============================================================================


def test_create_thread_run(test_client: TestClient, test_agent: Agent):
    """Test creating a background run on a thread."""
    # Create thread
    thread_resp = test_client.post("/ap/threads", json={})
    thread_id = thread_resp.json()["thread_id"]

    mock_output = RunOutput(
        run_id="test-run-123",
        session_id=thread_id,
        agent_id=test_agent.id,
        agent_name=test_agent.name,
        content="Test response",
        status=RunStatus.completed,
    )

    with patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_output

        response = test_client.post(
            f"/ap/threads/{thread_id}/runs",
            json={
                "assistant_id": test_agent.id,
                "input": {"messages": [{"role": "user", "content": "Hello"}]},
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert "run_id" in data
    assert data["thread_id"] == thread_id
    assert data["assistant_id"] == test_agent.id
    assert data["status"] in ("pending", "running", "success")


def test_get_thread_run(test_client: TestClient, test_agent: Agent):
    """Test getting a run's status."""
    thread_resp = test_client.post("/ap/threads", json={})
    thread_id = thread_resp.json()["thread_id"]

    mock_output = RunOutput(
        run_id="test-run-123",
        session_id=thread_id,
        agent_id=test_agent.id,
        agent_name=test_agent.name,
        content="Test response",
        status=RunStatus.completed,
    )

    with patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_output

        run_resp = test_client.post(
            f"/ap/threads/{thread_id}/runs",
            json={
                "assistant_id": test_agent.id,
                "input": {"messages": [{"role": "user", "content": "Hello"}]},
            },
        )

    run_id = run_resp.json()["run_id"]
    response = test_client.get(f"/ap/threads/{thread_id}/runs/{run_id}")
    assert response.status_code == 200
    assert response.json()["run_id"] == run_id


# ============================================================================
# Stateless Run Tests
# ============================================================================


def test_create_run_wait(test_client: TestClient, test_agent: Agent):
    """Test creating a stateless run and waiting for the result."""
    mock_output = RunOutput(
        run_id="test-run-123",
        agent_id=test_agent.id,
        agent_name=test_agent.name,
        content="Hello! This is a test response.",
        status=RunStatus.completed,
    )

    with patch.object(test_agent, "arun", new_callable=AsyncMock) as mock_arun:
        mock_arun.return_value = mock_output

        response = test_client.post(
            "/ap/runs/wait",
            json={
                "agent_id": test_agent.id,
                "input": {"messages": [{"role": "user", "content": "Hello"}]},
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert "run" in data
    assert data["run"]["status"] == "success"
    assert "values" in data
    assert "messages" in data


# ============================================================================
# Store Tests
# ============================================================================


def test_store_put_get(test_client: TestClient):
    """Test putting and getting a store item."""
    test_client.put(
        "/ap/store/items",
        json={"namespace": ["test", "ns"], "key": "my_key", "value": {"data": "hello"}},
    )

    response = test_client.get("/ap/store/items", params={"namespace": ["test", "ns"], "key": "my_key"})
    assert response.status_code == 200
    data = response.json()
    assert data["key"] == "my_key"
    assert data["value"]["data"] == "hello"


def test_store_delete(test_client: TestClient):
    """Test deleting a store item."""
    test_client.put(
        "/ap/store/items",
        json={"namespace": ["test"], "key": "to_delete", "value": {"data": "temp"}},
    )

    response = test_client.request(
        "DELETE",
        "/ap/store/items",
        json={"namespace": ["test"], "key": "to_delete"},
    )
    assert response.status_code == 200


def test_store_search(test_client: TestClient):
    """Test searching store items."""
    test_client.put(
        "/ap/store/items",
        json={"namespace": ["search", "test"], "key": "item1", "value": {"data": "a"}},
    )

    response = test_client.post(
        "/ap/store/items/search",
        json={"namespace_prefix": ["search"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
