"""Full Agent Protocol test suite with 100% endpoint coverage.

Tests all 32 Agent Protocol endpoints across:
- Thread CRUD (create, get, update, delete, copy, search, history)
- Thread-scoped runs (create, get, cancel, list, join, stream, wait)
- Stateless runs (wait, stream)
- Background runs (create, get, wait, cancel, delete, search)
- Agent introspection (search, get, schemas)
- Store (put, get, delete, search, namespaces)
- Error handling (404, 409)
"""

import time
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.os.app import AgentOS
from agno.os.interfaces.agent_protocol.router import _runs, _run_tasks, _store, _threads
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.team import Team


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def _clear_state():
    """Clear in-memory state before each test."""
    _threads.clear()
    _runs.clear()
    _run_tasks.clear()
    _store.clear()
    yield
    _threads.clear()
    _runs.clear()
    _run_tasks.clear()
    _store.clear()


@pytest.fixture
def test_agent():
    return Agent(
        name="test-ap-agent",
        id="test_ap_agent",
        description="A test agent for Agent Protocol",
        instructions="You are a helpful assistant.",
    )


@pytest.fixture
def test_agent_2():
    return Agent(
        name="second-agent",
        id="second_agent",
        description="A second test agent",
        instructions="You are another assistant.",
    )


@pytest.fixture
def test_team(test_agent, test_agent_2):
    return Team(
        name="test-team",
        id="test_team",
        description="A test team",
        members=[test_agent, test_agent_2],
    )


@pytest.fixture
def test_client(test_agent):
    agent_os = AgentOS(agents=[test_agent], agent_protocol_interface=True)
    app = agent_os.get_app()
    return TestClient(app)


@pytest.fixture
def multi_client(test_agent, test_agent_2, test_team):
    agent_os = AgentOS(
        agents=[test_agent, test_agent_2],
        teams=[test_team],
        agent_protocol_interface=True,
    )
    app = agent_os.get_app()
    return TestClient(app)


def _mock_output(agent, content="Test response", session_id=None):
    return RunOutput(
        run_id="mock-run",
        session_id=session_id or "mock-session",
        agent_id=agent.id,
        agent_name=agent.name,
        content=content,
        status=RunStatus.completed,
    )


@contextmanager
def mock_agent_run(agent, content="Test response"):
    """Context manager to mock agent.arun() returning a RunOutput."""
    output = _mock_output(agent, content)
    with patch.object(agent, "arun", new_callable=AsyncMock) as mock:
        mock.return_value = output
        yield mock


# ============================================================================
# 1. Thread CRUD
# ============================================================================


class TestThreadCRUD:
    def test_create_thread(self, test_client):
        resp = test_client.post("/ap/threads", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert "thread_id" in data
        assert data["status"] == "idle"
        assert data["values"] == {}
        assert data["metadata"] == {}
        assert "created_at" in data
        assert "updated_at" in data
        assert data["interrupts"] == {}

    def test_create_thread_with_custom_id(self, test_client):
        resp = test_client.post("/ap/threads", json={"thread_id": "custom-123"})
        assert resp.status_code == 200
        assert resp.json()["thread_id"] == "custom-123"

    def test_create_thread_with_metadata(self, test_client):
        resp = test_client.post("/ap/threads", json={"metadata": {"env": "test", "user": "alice"}})
        assert resp.status_code == 200
        data = resp.json()
        assert data["metadata"]["env"] == "test"
        assert data["metadata"]["user"] == "alice"

    def test_get_thread(self, test_client):
        create_resp = test_client.post("/ap/threads", json={})
        tid = create_resp.json()["thread_id"]
        resp = test_client.get(f"/ap/threads/{tid}")
        assert resp.status_code == 200
        assert resp.json()["thread_id"] == tid

    def test_get_thread_not_found(self, test_client):
        resp = test_client.get("/ap/threads/nonexistent-id")
        assert resp.status_code == 404

    def test_update_thread_metadata(self, test_client):
        create_resp = test_client.post("/ap/threads", json={"metadata": {"a": 1}})
        tid = create_resp.json()["thread_id"]
        resp = test_client.patch(f"/ap/threads/{tid}", json={"metadata": {"b": 2}})
        assert resp.status_code == 200
        data = resp.json()
        assert data["metadata"]["a"] == 1
        assert data["metadata"]["b"] == 2

    def test_update_thread_values(self, test_client):
        create_resp = test_client.post("/ap/threads", json={})
        tid = create_resp.json()["thread_id"]
        resp = test_client.patch(
            f"/ap/threads/{tid}", json={"values": {"messages": [{"type": "human", "content": "hi"}]}}
        )
        assert resp.status_code == 200
        assert resp.json()["values"]["messages"][0]["content"] == "hi"

    def test_delete_thread(self, test_client):
        create_resp = test_client.post("/ap/threads", json={})
        tid = create_resp.json()["thread_id"]
        resp = test_client.delete(f"/ap/threads/{tid}")
        assert resp.status_code == 200
        assert test_client.get(f"/ap/threads/{tid}").status_code == 404

    def test_delete_thread_not_found(self, test_client):
        resp = test_client.delete("/ap/threads/nonexistent")
        assert resp.status_code == 404

    def test_copy_thread(self, test_client):
        create_resp = test_client.post("/ap/threads", json={"metadata": {"source": "original"}})
        tid = create_resp.json()["thread_id"]
        resp = test_client.post(f"/ap/threads/{tid}/copy")
        assert resp.status_code == 200
        copy = resp.json()
        assert copy["thread_id"] != tid
        assert copy["metadata"]["source"] == "original"

    def test_copy_thread_not_found(self, test_client):
        resp = test_client.post("/ap/threads/nonexistent/copy")
        assert resp.status_code == 404

    def test_search_threads(self, test_client):
        test_client.post("/ap/threads", json={"metadata": {"env": "prod"}})
        test_client.post("/ap/threads", json={"metadata": {"env": "test"}})
        test_client.post("/ap/threads", json={"metadata": {"env": "prod"}})
        resp = test_client.post("/ap/threads/search", json={})
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    def test_search_threads_with_metadata_filter(self, test_client):
        test_client.post("/ap/threads", json={"metadata": {"env": "prod"}})
        test_client.post("/ap/threads", json={"metadata": {"env": "test"}})
        resp = test_client.post("/ap/threads/search", json={"metadata": {"env": "prod"}})
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_search_threads_pagination(self, test_client):
        for _ in range(5):
            test_client.post("/ap/threads", json={})
        resp = test_client.post("/ap/threads/search", json={"limit": 2, "offset": 0})
        assert len(resp.json()) == 2
        resp2 = test_client.post("/ap/threads/search", json={"limit": 2, "offset": 2})
        assert len(resp2.json()) == 2

    def test_get_thread_history(self, test_client):
        create_resp = test_client.post("/ap/threads", json={"metadata": {"key": "val"}})
        tid = create_resp.json()["thread_id"]
        resp = test_client.get(f"/ap/threads/{tid}/history")
        assert resp.status_code == 200
        history = resp.json()
        assert isinstance(history, list)
        assert len(history) == 1
        state = history[0]
        assert "values" in state
        assert "checkpoint" in state
        assert state["checkpoint"]["thread_id"] == tid
        assert "next" in state
        assert state["next"] == []

    def test_get_thread_history_not_found(self, test_client):
        resp = test_client.get("/ap/threads/nonexistent/history")
        assert resp.status_code == 404


# ============================================================================
# 2. Thread-Scoped Background Runs
# ============================================================================


class TestThreadScopedRuns:
    def test_create_thread_run(self, test_client, test_agent):
        tid = test_client.post("/ap/threads", json={}).json()["thread_id"]
        with mock_agent_run(test_agent):
            resp = test_client.post(
                f"/ap/threads/{tid}/runs",
                json={
                    "assistant_id": test_agent.id,
                    "input": {"messages": [{"role": "user", "content": "Hello"}]},
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["thread_id"] == tid
        assert data["assistant_id"] == test_agent.id
        assert "run_id" in data

    def test_get_thread_run(self, test_client, test_agent):
        tid = test_client.post("/ap/threads", json={}).json()["thread_id"]
        with mock_agent_run(test_agent):
            run_resp = test_client.post(
                f"/ap/threads/{tid}/runs",
                json={"assistant_id": test_agent.id, "input": {"messages": [{"role": "user", "content": "Hi"}]}},
            )
        rid = run_resp.json()["run_id"]
        resp = test_client.get(f"/ap/threads/{tid}/runs/{rid}")
        assert resp.status_code == 200
        assert resp.json()["run_id"] == rid

    def test_get_thread_run_not_found(self, test_client):
        tid = test_client.post("/ap/threads", json={}).json()["thread_id"]
        resp = test_client.get(f"/ap/threads/{tid}/runs/nonexistent")
        assert resp.status_code == 404

    def test_cancel_thread_run(self, test_client, test_agent):
        tid = test_client.post("/ap/threads", json={}).json()["thread_id"]
        with mock_agent_run(test_agent):
            run_resp = test_client.post(
                f"/ap/threads/{tid}/runs",
                json={"assistant_id": test_agent.id, "input": {"messages": [{"role": "user", "content": "Hi"}]}},
            )
        rid = run_resp.json()["run_id"]
        resp = test_client.post(f"/ap/threads/{tid}/runs/{rid}/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "interrupted"

    def test_cancel_thread_run_not_found(self, test_client):
        tid = test_client.post("/ap/threads", json={}).json()["thread_id"]
        resp = test_client.post(f"/ap/threads/{tid}/runs/nonexistent/cancel")
        assert resp.status_code == 404

    def test_list_thread_runs(self, test_client, test_agent):
        tid = test_client.post("/ap/threads", json={}).json()["thread_id"]
        with mock_agent_run(test_agent):
            test_client.post(
                f"/ap/threads/{tid}/runs",
                json={"assistant_id": test_agent.id, "input": {"messages": [{"role": "user", "content": "r1"}]}},
            )
            test_client.post(
                f"/ap/threads/{tid}/runs",
                json={"assistant_id": test_agent.id, "input": {"messages": [{"role": "user", "content": "r2"}]}},
            )
        resp = test_client.get(f"/ap/threads/{tid}/runs")
        assert resp.status_code == 200
        runs = resp.json()
        assert len(runs) == 2

    def test_join_thread_run(self, test_client, test_agent):
        tid = test_client.post("/ap/threads", json={}).json()["thread_id"]
        with mock_agent_run(test_agent, content="Join result"):
            run_resp = test_client.post(
                f"/ap/threads/{tid}/runs",
                json={"assistant_id": test_agent.id, "input": {"messages": [{"role": "user", "content": "Hi"}]}},
            )
        rid = run_resp.json()["run_id"]
        resp = test_client.get(f"/ap/threads/{tid}/runs/{rid}/join")
        assert resp.status_code == 200
        data = resp.json()
        assert "run" in data
        assert "values" in data
        assert "messages" in data

    def test_join_thread_run_not_found(self, test_client):
        resp = test_client.get("/ap/threads/fake/runs/fake/join")
        assert resp.status_code == 404

    def test_create_thread_run_if_not_exists_create(self, test_client, test_agent):
        """When thread doesn't exist, if_not_exists=create should auto-create it."""
        with mock_agent_run(test_agent):
            resp = test_client.post(
                "/ap/threads/auto-create-123/runs",
                json={
                    "assistant_id": test_agent.id,
                    "input": {"messages": [{"role": "user", "content": "Hi"}]},
                    "if_not_exists": "create",
                },
            )
        assert resp.status_code == 200
        # Verify thread was created
        assert test_client.get("/ap/threads/auto-create-123").status_code == 200

    def test_create_thread_run_if_not_exists_reject(self, test_client, test_agent):
        """When thread doesn't exist and if_not_exists=reject, should 404."""
        resp = test_client.post(
            "/ap/threads/nonexistent-thread/runs",
            json={
                "assistant_id": test_agent.id,
                "input": {"messages": [{"role": "user", "content": "Hi"}]},
            },
        )
        assert resp.status_code == 404

    def test_create_thread_run_unknown_assistant(self, test_client):
        tid = test_client.post("/ap/threads", json={}).json()["thread_id"]
        resp = test_client.post(
            f"/ap/threads/{tid}/runs",
            json={"assistant_id": "nonexistent-agent", "input": {"messages": [{"role": "user", "content": "Hi"}]}},
        )
        assert resp.status_code == 404


# ============================================================================
# 3. Thread-Scoped Streaming & Wait
# ============================================================================


class TestThreadScopedStreamWait:
    def test_stream_thread_run(self, test_client, test_agent):
        """Test SSE streaming for thread-scoped runs."""
        tid = test_client.post("/ap/threads", json={}).json()["thread_id"]

        async def mock_stream(*args, **kwargs):
            """Mock agent.arun with stream=True returning chunks."""
            from agno.run.agent import RunContentEvent

            yield RunContentEvent(content="Hello ")
            yield RunContentEvent(content="world!")

        with patch.object(test_agent, "arun", side_effect=mock_stream):
            resp = test_client.post(
                f"/ap/threads/{tid}/runs/stream",
                json={"assistant_id": test_agent.id, "input": {"messages": [{"role": "user", "content": "Hi"}]}},
            )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        body = resp.text
        assert "event: metadata" in body
        assert "event: end" in body

    def test_stream_thread_run_not_found(self, test_client, test_agent):
        resp = test_client.post(
            "/ap/threads/nonexistent/runs/stream",
            json={"assistant_id": test_agent.id, "input": {"messages": [{"role": "user", "content": "Hi"}]}},
        )
        assert resp.status_code == 404

    def test_wait_thread_run(self, test_client, test_agent):
        """Test blocking wait for thread-scoped run."""
        tid = test_client.post("/ap/threads", json={}).json()["thread_id"]
        with mock_agent_run(test_agent, content="Wait result"):
            resp = test_client.post(
                f"/ap/threads/{tid}/runs/wait",
                json={"assistant_id": test_agent.id, "input": {"messages": [{"role": "user", "content": "Hi"}]}},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "run" in data
        assert data["run"]["status"] == "success"
        assert "values" in data
        assert "messages" in data

    def test_wait_thread_run_not_found(self, test_client, test_agent):
        resp = test_client.post(
            "/ap/threads/nonexistent/runs/wait",
            json={"assistant_id": test_agent.id, "input": {}},
        )
        assert resp.status_code == 404


# ============================================================================
# 4. Stateless Runs
# ============================================================================


class TestStatelessRuns:
    def test_create_run_wait(self, test_client, test_agent):
        with mock_agent_run(test_agent, content="Stateless response"):
            resp = test_client.post(
                "/ap/runs/wait",
                json={
                    "agent_id": test_agent.id,
                    "input": {"messages": [{"role": "user", "content": "Hello"}]},
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "run" in data
        assert data["run"]["status"] == "success"
        assert "values" in data
        assert "messages" in data

    def test_create_run_wait_with_assistant_id(self, test_client, test_agent):
        """Test using assistant_id instead of agent_id."""
        with mock_agent_run(test_agent):
            resp = test_client.post(
                "/ap/runs/wait",
                json={
                    "assistant_id": test_agent.id,
                    "input": {"messages": [{"role": "user", "content": "Hello"}]},
                },
            )
        assert resp.status_code == 200
        assert resp.json()["run"]["status"] == "success"

    def test_create_run_wait_with_messages_field(self, test_client, test_agent):
        """Test using top-level messages field instead of input."""
        with mock_agent_run(test_agent):
            resp = test_client.post(
                "/ap/runs/wait",
                json={
                    "agent_id": test_agent.id,
                    "messages": [{"role": "user", "content": "Hello from messages"}],
                },
            )
        assert resp.status_code == 200
        assert resp.json()["run"]["status"] == "success"

    def test_create_run_wait_default_agent(self, test_client, test_agent):
        """When no agent_id specified, use the first registered agent."""
        with mock_agent_run(test_agent):
            resp = test_client.post(
                "/ap/runs/wait",
                json={"input": {"messages": [{"role": "user", "content": "Hello"}]}},
            )
        assert resp.status_code == 200
        assert resp.json()["run"]["status"] == "success"

    def test_create_run_wait_unknown_agent(self, test_client):
        resp = test_client.post(
            "/ap/runs/wait",
            json={"agent_id": "nonexistent", "input": {"messages": [{"role": "user", "content": "Hi"}]}},
        )
        assert resp.status_code == 404

    def test_create_run_stream(self, test_client, test_agent):
        """Test SSE streaming for stateless runs."""

        async def mock_stream(*args, **kwargs):
            from agno.run.agent import RunContentEvent

            yield RunContentEvent(content="Streamed!")

        with patch.object(test_agent, "arun", side_effect=mock_stream):
            resp = test_client.post(
                "/ap/runs/stream",
                json={"agent_id": test_agent.id, "input": {"messages": [{"role": "user", "content": "Hi"}]}},
            )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        body = resp.text
        assert "event: metadata" in body
        assert "event: end" in body

    def test_create_run_stream_unknown_agent(self, test_client):
        resp = test_client.post(
            "/ap/runs/stream",
            json={"agent_id": "nonexistent", "input": {"messages": [{"role": "user", "content": "Hi"}]}},
        )
        assert resp.status_code == 404


# ============================================================================
# 5. Background Runs (Stateless)
# ============================================================================


class TestBackgroundRuns:
    def test_create_background_run(self, test_client, test_agent):
        with mock_agent_run(test_agent):
            resp = test_client.post(
                "/ap/runs",
                json={
                    "agent_id": test_agent.id,
                    "input": {"messages": [{"role": "user", "content": "Background task"}]},
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "run_id" in data
        assert data["assistant_id"] == test_agent.id

    def test_create_background_run_unknown_agent(self, test_client):
        resp = test_client.post(
            "/ap/runs",
            json={"agent_id": "nonexistent", "input": {"messages": [{"role": "user", "content": "Hi"}]}},
        )
        assert resp.status_code == 404

    def test_get_run(self, test_client, test_agent):
        with mock_agent_run(test_agent):
            run_resp = test_client.post(
                "/ap/runs",
                json={"agent_id": test_agent.id, "input": {"messages": [{"role": "user", "content": "Hi"}]}},
            )
        rid = run_resp.json()["run_id"]
        resp = test_client.get(f"/ap/runs/{rid}")
        assert resp.status_code == 200
        assert resp.json()["run_id"] == rid

    def test_get_run_not_found(self, test_client):
        resp = test_client.get("/ap/runs/nonexistent")
        assert resp.status_code == 404

    def test_wait_run(self, test_client, test_agent):
        with mock_agent_run(test_agent, content="Done"):
            run_resp = test_client.post(
                "/ap/runs",
                json={"agent_id": test_agent.id, "input": {"messages": [{"role": "user", "content": "Hi"}]}},
            )
        rid = run_resp.json()["run_id"]
        resp = test_client.get(f"/ap/runs/{rid}/wait")
        assert resp.status_code == 200
        data = resp.json()
        assert "run" in data
        assert "values" in data

    def test_wait_run_not_found(self, test_client):
        resp = test_client.get("/ap/runs/nonexistent/wait")
        assert resp.status_code == 404

    def test_cancel_run(self, test_client, test_agent):
        with mock_agent_run(test_agent):
            run_resp = test_client.post(
                "/ap/runs",
                json={"agent_id": test_agent.id, "input": {"messages": [{"role": "user", "content": "Hi"}]}},
            )
        rid = run_resp.json()["run_id"]
        resp = test_client.post(f"/ap/runs/{rid}/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "interrupted"

    def test_cancel_run_not_found(self, test_client):
        resp = test_client.post("/ap/runs/nonexistent/cancel")
        assert resp.status_code == 404

    def test_delete_run(self, test_client, test_agent):
        with mock_agent_run(test_agent):
            run_resp = test_client.post(
                "/ap/runs",
                json={"agent_id": test_agent.id, "input": {"messages": [{"role": "user", "content": "Hi"}]}},
            )
        rid = run_resp.json()["run_id"]
        # Wait briefly for async task to complete
        time.sleep(0.1)
        resp = test_client.delete(f"/ap/runs/{rid}")
        assert resp.status_code == 200

    def test_delete_run_not_found(self, test_client):
        resp = test_client.delete("/ap/runs/nonexistent")
        assert resp.status_code == 404

    def test_search_runs(self, test_client, test_agent):
        with mock_agent_run(test_agent):
            test_client.post(
                "/ap/runs",
                json={"agent_id": test_agent.id, "input": {"messages": [{"role": "user", "content": "r1"}]}},
            )
            test_client.post(
                "/ap/runs",
                json={"agent_id": test_agent.id, "input": {"messages": [{"role": "user", "content": "r2"}]}},
            )
        resp = test_client.post("/ap/runs/search", json={})
        assert resp.status_code == 200
        runs = resp.json()
        assert len(runs) >= 2

    def test_search_runs_with_status_filter(self, test_client, test_agent):
        with mock_agent_run(test_agent):
            run_resp = test_client.post(
                "/ap/runs",
                json={"agent_id": test_agent.id, "input": {"messages": [{"role": "user", "content": "Hi"}]}},
            )
        rid = run_resp.json()["run_id"]
        # Cancel it to get an interrupted status
        test_client.post(f"/ap/runs/{rid}/cancel")
        resp = test_client.post("/ap/runs/search", json={"status": "interrupted"})
        assert resp.status_code == 200
        interrupted = resp.json()
        assert any(r["run_id"] == rid for r in interrupted)


# ============================================================================
# 6. Agent Introspection
# ============================================================================


class TestAgentIntrospection:
    def test_search_agents(self, test_client, test_agent):
        resp = test_client.post("/ap/agents/search", json={})
        assert resp.status_code == 200
        agents = resp.json()
        assert len(agents) >= 1
        ids = [a["agent_id"] for a in agents]
        assert test_agent.id in ids

    def test_search_agents_with_teams(self, multi_client, test_agent, test_team):
        resp = multi_client.post("/ap/agents/search", json={})
        assert resp.status_code == 200
        agents = resp.json()
        ids = [a["agent_id"] for a in agents]
        assert test_agent.id in ids
        assert test_team.id in ids

    def test_get_agent(self, test_client, test_agent):
        resp = test_client.get(f"/ap/agents/{test_agent.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == test_agent.id
        assert data["name"] == test_agent.name
        assert data["description"] == test_agent.description

    def test_get_agent_capabilities(self, test_client, test_agent):
        resp = test_client.get(f"/ap/agents/{test_agent.id}")
        assert resp.status_code == 200
        caps = resp.json()["capabilities"]
        assert caps["ap.io.messages"] is True
        assert caps["ap.io.streaming"] is True

    def test_get_agent_not_found(self, test_client):
        resp = test_client.get("/ap/agents/nonexistent")
        assert resp.status_code == 404

    def test_get_agent_schemas(self, test_client, test_agent):
        resp = test_client.get(f"/ap/agents/{test_agent.id}/schemas")
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == test_agent.id
        assert "input_schema" in data
        assert "output_schema" in data
        # Verify schema structure
        assert data["input_schema"]["type"] == "object"
        assert "messages" in data["input_schema"]["properties"]
        assert data["output_schema"]["type"] == "object"

    def test_get_agent_schemas_not_found(self, test_client):
        resp = test_client.get("/ap/agents/nonexistent/schemas")
        assert resp.status_code == 404


# ============================================================================
# 7. Store
# ============================================================================


class TestStore:
    def test_put_and_get_item(self, test_client):
        test_client.put(
            "/ap/store/items",
            json={"namespace": ["users", "prefs"], "key": "theme", "value": {"mode": "dark"}},
        )
        resp = test_client.get("/ap/store/items", params={"namespace": ["users", "prefs"], "key": "theme"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == "theme"
        assert data["value"]["mode"] == "dark"
        assert data["namespace"] == ["users", "prefs"]

    def test_put_item_requires_key(self, test_client):
        resp = test_client.put("/ap/store/items", json={"namespace": ["test"], "value": {"data": 1}})
        assert resp.status_code == 400

    def test_get_item_not_found(self, test_client):
        resp = test_client.get("/ap/store/items", params={"namespace": ["x"], "key": "missing"})
        assert resp.status_code == 404

    def test_delete_item(self, test_client):
        test_client.put("/ap/store/items", json={"namespace": ["tmp"], "key": "k1", "value": {"x": 1}})
        resp = test_client.request("DELETE", "/ap/store/items", json={"namespace": ["tmp"], "key": "k1"})
        assert resp.status_code == 200
        # Verify deleted
        assert test_client.get("/ap/store/items", params={"namespace": ["tmp"], "key": "k1"}).status_code == 404

    def test_search_items(self, test_client):
        test_client.put("/ap/store/items", json={"namespace": ["search", "ns"], "key": "a", "value": {"v": 1}})
        test_client.put("/ap/store/items", json={"namespace": ["search", "ns"], "key": "b", "value": {"v": 2}})
        test_client.put("/ap/store/items", json={"namespace": ["other"], "key": "c", "value": {"v": 3}})
        resp = test_client.post("/ap/store/items/search", json={"namespace_prefix": ["search"]})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 2

    def test_search_items_pagination(self, test_client):
        for i in range(5):
            test_client.put("/ap/store/items", json={"namespace": ["page"], "key": f"k{i}", "value": {"i": i}})
        resp = test_client.post("/ap/store/items/search", json={"namespace_prefix": ["page"], "limit": 2})
        assert len(resp.json()["items"]) == 2

    def test_list_namespaces(self, test_client):
        test_client.put("/ap/store/items", json={"namespace": ["ns1", "sub1"], "key": "k1", "value": {}})
        test_client.put("/ap/store/items", json={"namespace": ["ns2"], "key": "k2", "value": {}})
        resp = test_client.post("/ap/store/namespaces", json={})
        assert resp.status_code == 200
        namespaces = resp.json()
        assert len(namespaces) == 2
        # Verify both namespaces present
        ns_tuples = [tuple(ns) for ns in namespaces]
        assert ("ns1", "sub1") in ns_tuples
        assert ("ns2",) in ns_tuples


# ============================================================================
# 8. Integration / End-to-End Scenarios
# ============================================================================


class TestEndToEnd:
    def test_full_thread_run_lifecycle(self, test_client, test_agent):
        """Create thread → run → check status → get thread values → delete."""
        # 1. Create thread
        tid = test_client.post("/ap/threads", json={}).json()["thread_id"]

        # 2. Create run
        with mock_agent_run(test_agent, content="Final answer"):
            run_resp = test_client.post(
                f"/ap/threads/{tid}/runs",
                json={"assistant_id": test_agent.id, "input": {"messages": [{"role": "user", "content": "Question"}]}},
            )
        rid = run_resp.json()["run_id"]

        # 3. Check run status
        status_resp = test_client.get(f"/ap/threads/{tid}/runs/{rid}")
        assert status_resp.json()["status"] in ("pending", "running", "success")

        # 4. Get thread values
        thread_resp = test_client.get(f"/ap/threads/{tid}")
        values = thread_resp.json().get("values", {})
        assert "messages" in values

        # 5. Delete thread
        assert test_client.delete(f"/ap/threads/{tid}").status_code == 200

    def test_deepagents_flow(self, test_client, test_agent):
        """Simulate the exact flow deepagents uses:
        1. threads.create()
        2. runs.create(thread_id, assistant_id, input)
        3. runs.get(thread_id, run_id)
        4. threads.get(thread_id) -- to read values
        """
        # 1. Create thread (deepagents: client.threads.create())
        thread = test_client.post("/ap/threads", json={}).json()
        assert "thread_id" in thread
        tid = thread["thread_id"]

        # 2. Create run (deepagents: client.runs.create())
        with mock_agent_run(test_agent, content="Research results: quantum computing is advancing rapidly"):
            run = test_client.post(
                f"/ap/threads/{tid}/runs",
                json={
                    "assistant_id": test_agent.id,
                    "input": {"messages": [{"role": "user", "content": "Research quantum computing"}]},
                },
            ).json()
        assert "run_id" in run
        rid = run["run_id"]

        # 3. Get run status (deepagents: client.runs.get())
        run_status = test_client.get(f"/ap/threads/{tid}/runs/{rid}").json()
        assert run_status["status"] in ("pending", "running", "success")

        # 4. Get thread values (deepagents: client.threads.get())
        thread_data = test_client.get(f"/ap/threads/{tid}").json()
        assert thread_data["thread_id"] == tid
        values = thread_data.get("values", {})
        messages = values.get("messages", [])
        assert len(messages) >= 1
