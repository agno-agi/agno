"""System tests for AgentOS stateless deployment."""

import time
from typing import Set

import pytest
import requests

# Base URL for the nginx load balancer
BASE_URL = "http://localhost:8080"

# Test timeout
REQUEST_TIMEOUT = 30


@pytest.fixture(scope="class", autouse=True)
def wait_for_services():
    """Wait for all services to be healthy before running tests."""
    max_retries = 30
    retry_delay = 2

    for i in range(max_retries):
        try:
            response = requests.get(f"{BASE_URL}/health", timeout=5)
            if response.status_code == 200:
                print("✓ All services are healthy")
                # Give extra time for database migrations
                time.sleep(5)
                return
        except requests.exceptions.RequestException:
            pass

        if i < max_retries - 1:
            print(f"Waiting for services to be ready... ({i + 1}/{max_retries})")
            time.sleep(retry_delay)

    pytest.fail("Services did not become healthy in time")


def test_health_check():
    """Test that the health check endpoint returns a 200 status code."""
    response = requests.get(f"{BASE_URL}/health", timeout=REQUEST_TIMEOUT)
    assert response.status_code == 200, f"Health check failed: {response.status_code}"
    assert response.json().get("status") == "ok", f"Health check returned unhealthy status: {response.json()}"


def test_multiple_containers_responding():
    """Test that requests are distributed across multiple containers."""
    containers_seen: Set[str] = set()
    num_requests = 20

    for i in range(num_requests):
        try:
            response = requests.get(
                f"{BASE_URL}/config",
                timeout=REQUEST_TIMEOUT,
            )
            assert response.status_code == 200, f"Request {i + 1} failed with status {response.status_code}"

            data = response.json()
            container_id = data.get("container_id")
            assert container_id, f"No container_id in response: {data}"

            containers_seen.add(container_id)
            print(f"Request {i + 1}: Container {container_id}")

        except requests.exceptions.RequestException as e:
            pytest.fail(f"Request {i + 1} failed: {e}")

    # We should see at least 2 different containers (ideally all 3)
    assert len(containers_seen) >= 2, (
        f"Expected at least 2 different containers, but only saw {len(containers_seen)}: {containers_seen}"
    )
    print(f"✓ Requests distributed across {len(containers_seen)} containers: {containers_seen}")


def test_create_and_retrieve_session_stateless():
    """Test creating a session on one container and retrieving it from another."""
    # Step 1: Create a session
    create_response = requests.post(
        f"{BASE_URL}/sessions",
        params={"type": "agent"},
        json={
            "agent_id": "test-agent",
            "session_name": "Stateless Test Session",
            "session_state": {"test_key": "test_value"},
        },
        timeout=REQUEST_TIMEOUT,
    )

    assert create_response.status_code == 201, (
        f"Failed to create session: {create_response.status_code} - {create_response.text}"
    )

    session_data = create_response.json()
    session_id = session_data["session_id"]
    print(f"✓ Created session: {session_id}")

    # Step 2: Retrieve the session multiple times (likely from different containers)
    containers_that_retrieved: Set[str] = set()

    for i in range(10):
        retrieve_response = requests.get(
            f"{BASE_URL}/sessions/{session_id}",
            params={"type": "agent"},
            timeout=REQUEST_TIMEOUT,
        )

        assert retrieve_response.status_code == 200, (
            f"Failed to retrieve session on attempt {i + 1}: {retrieve_response.status_code} - {retrieve_response.text}"
        )

        retrieved_data = retrieve_response.json()
        assert retrieved_data["session_id"] == session_id
        assert retrieved_data["session_name"] == "Stateless Test Session"
        assert retrieved_data.get("session_state", {}).get("test_key") == "test_value"

        # Track which container responded
        container_header = retrieve_response.headers.get("X-Container-ID", "unknown")
        containers_that_retrieved.add(container_header)

        print(f"  Attempt {i + 1}: Retrieved from container at {container_header}")

    print(f"✓ Session retrieved successfully from {len(containers_that_retrieved)} different containers")

    # Step 3: Clean up
    delete_response = requests.delete(
        f"{BASE_URL}/sessions/{session_id}",
        timeout=REQUEST_TIMEOUT,
    )
    assert delete_response.status_code == 204, f"Failed to delete session: {delete_response.status_code}"
    print(f"✓ Cleaned up session: {session_id}")


def test_run_agent_creates_session_stateless():
    """Test running an agent creates a session that can be accessed from any container."""
    # Step 1: Run the agent with a specific session_id
    session_id = f"test-session-{int(time.time())}"
    message = "Hello, please introduce yourself briefly."

    run_response = requests.post(
        f"{BASE_URL}/agents/test-agent/runs",
        data={
            "message": message,
            "session_id": session_id,
            "stream": "false",
        },
        timeout=REQUEST_TIMEOUT,
    )

    assert run_response.status_code == 200, f"Failed to run agent: {run_response.status_code} - {run_response.text}"

    run_data = run_response.json()
    assert "content" in run_data, f"No content in run response: {run_data}"

    content = run_data["content"]
    assert isinstance(content, str) and len(content) > 0, f"Invalid content: {content}"

    print(f"✓ Agent run successful with session: {session_id}")
    print(f"  Response: {content[:100]}...")

    # Step 2: Verify the session exists and can be retrieved from different containers
    containers_that_retrieved: Set[str] = set()

    for i in range(10):
        session_response = requests.get(
            f"{BASE_URL}/sessions/{session_id}",
            params={"type": "agent"},
            timeout=REQUEST_TIMEOUT,
        )

        assert session_response.status_code == 200, (
            f"Failed to retrieve session on attempt {i + 1}: {session_response.status_code} - {session_response.text}"
        )

        session_data = session_response.json()
        assert session_data["session_id"] == session_id
        assert session_data["agent_id"] == "test-agent"
        assert "chat_history" in session_data
        assert len(session_data["chat_history"]) > 0, "Session should have chat history"

        # Track which container responded
        container_header = session_response.headers.get("X-Container-ID", "unknown")
        containers_that_retrieved.add(container_header)

        print(f"  Attempt {i + 1}: Retrieved session from container at {container_header}")

    print(f"✓ Session retrieved from {len(containers_that_retrieved)} different containers")

    # Step 3: Run another message in the same session from potentially different container
    second_message = "What is 2 + 2?"

    second_run_response = requests.post(
        f"{BASE_URL}/agents/test-agent/runs",
        data={
            "message": second_message,
            "session_id": session_id,
            "stream": "false",
        },
        timeout=REQUEST_TIMEOUT,
    )

    assert second_run_response.status_code == 200, (
        f"Failed to run agent second time: {second_run_response.status_code} - {second_run_response.text}"
    )

    second_run_data = second_run_response.json()
    assert "content" in second_run_data

    print("✓ Second message processed successfully")
    print(f"  Response: {second_run_data['content'][:100]}...")

    # Step 4: Verify session now has history from both runs
    final_session_response = requests.get(
        f"{BASE_URL}/sessions/{session_id}",
        params={"type": "agent"},
        timeout=REQUEST_TIMEOUT,
    )

    assert final_session_response.status_code == 200
    final_session_data = final_session_response.json()

    # Should have at least 4 messages: system + 2 user messages + 2 assistant responses
    chat_history = final_session_data.get("chat_history", [])
    user_messages = [msg for msg in chat_history if msg.get("role") == "user"]

    assert len(user_messages) >= 2, f"Expected at least 2 user messages in history, got {len(user_messages)}"

    print(f"✓ Session history preserved across runs: {len(chat_history)} total messages")

    # Step 5: Clean up
    delete_response = requests.delete(
        f"{BASE_URL}/sessions/{session_id}",
        timeout=REQUEST_TIMEOUT,
    )
    assert delete_response.status_code == 204
    print(f"✓ Cleaned up session: {session_id}")


def test_concurrent_sessions_across_containers():
    """Test that multiple concurrent sessions work correctly across containers."""
    num_sessions = 5
    sessions_created = []

    # Create multiple sessions
    for i in range(num_sessions):
        response = requests.post(
            f"{BASE_URL}/sessions",
            params={"type": "agent"},
            json={
                "agent_id": "test-agent",
                "session_name": f"Concurrent Session {i + 1}",
                "session_state": {"session_number": i + 1},
            },
            timeout=REQUEST_TIMEOUT,
        )

        assert response.status_code == 201, f"Failed to create session {i + 1}"
        session_data = response.json()
        sessions_created.append(session_data["session_id"])

    print(f"✓ Created {len(sessions_created)} concurrent sessions")

    # Verify all sessions can be retrieved
    for i, session_id in enumerate(sessions_created):
        response = requests.get(
            f"{BASE_URL}/sessions/{session_id}",
            params={"type": "agent"},
            timeout=REQUEST_TIMEOUT,
        )

        assert response.status_code == 200, f"Failed to retrieve session {session_id}"
        data = response.json()
        assert data["session_id"] == session_id
        assert data["session_name"] == f"Concurrent Session {i + 1}"
        assert data.get("session_state", {}).get("session_number") == i + 1

    print(f"✓ All {len(sessions_created)} sessions retrieved successfully")

    # Clean up all sessions
    for session_id in sessions_created:
        requests.delete(
            f"{BASE_URL}/sessions/{session_id}",
            timeout=REQUEST_TIMEOUT,
        )

    print(f"✓ Cleaned up all {len(sessions_created)} sessions")


def test_health_check_all_containers():
    """Test that health check works and returns from all containers."""
    containers_seen: Set[str] = set()

    for i in range(15):
        response = requests.get(f"{BASE_URL}/health", timeout=REQUEST_TIMEOUT)

        assert response.status_code == 200, f"Health check failed: {response.status_code}"

        data = response.json()
        assert data.get("status") == "ok", f"Health check returned unhealthy status: {data}"

        container_header = response.headers.get("X-Container-ID", "unknown")
        containers_seen.add(container_header)

    print(f"✓ Health checks successful across {len(containers_seen)} containers")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
