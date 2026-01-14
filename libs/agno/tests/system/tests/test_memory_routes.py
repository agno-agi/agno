"""
System Tests for AgentOS Memory Routes.

Run with: pytest test_memory_routes.py -v --tb=short
"""

import uuid

import httpx
import pytest

from .test_utils import REQUEST_TIMEOUT, generate_jwt_token


@pytest.fixture(scope="module")
def test_user_id() -> str:
    """Generate a unique user ID for testing."""
    return f"test-user-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def client(gateway_url: str, test_user_id: str) -> httpx.Client:
    """Create an HTTP client for the gateway server with authentication."""
    return httpx.Client(
        base_url=gateway_url,
        timeout=REQUEST_TIMEOUT,
        headers={"Authorization": f"Bearer {generate_jwt_token(audience='gateway-os', user_id=test_user_id)}"},
    )


# =============================================================================
# Memory Routes Tests - With Agent Run Setup
# =============================================================================


class TestMemoryRoutesWithLocalAgent:
    """Test memory routes with local agent (gateway-agent)."""

    AGENT_ID = "gateway-agent"
    DB_ID = "gateway-db"

    @pytest.fixture(scope="class")
    def agent_run_for_memory(self, client: httpx.Client, test_user_id: str) -> dict:
        """Run the local agent to potentially generate memories."""
        session_id = str(uuid.uuid4())
        response = client.post(
            f"/agents/{self.AGENT_ID}/runs",
            data={
                "message": "My favorite programming language is Python and I prefer dark mode.",
                "stream": "false",
                "session_id": session_id,
                "user_id": test_user_id,
            },
        )
        assert response.status_code == 200
        return {
            "session_id": session_id,
            "user_id": test_user_id,
            "agent_id": self.AGENT_ID,
        }

    @pytest.fixture(scope="class")
    def created_memory_id(self, client: httpx.Client, test_user_id: str) -> str:
        """Create a memory for testing CRUD operations."""
        response = client.post(
            f"/memories?db_id={self.DB_ID}",
            json={
                "memory": "Local user prefers TypeScript over JavaScript for frontend development.",
                "topics": ["programming", "preferences", "frontend", "local"],
                "user_id": test_user_id,
            },
        )
        assert response.status_code == 200
        return response.json()["memory_id"]

    def test_create_memory_with_topics(self, client: httpx.Client, test_user_id: str, agent_run_for_memory: dict):
        """Test POST /memories creates memory with topics for local agent user."""
        response = client.post(
            f"/memories?db_id={self.DB_ID}",
            json={
                "memory": "Local user likes Python and FastAPI for backend development.",
                "topics": ["programming", "python", "frameworks", "backend", "local"],
                "user_id": test_user_id,
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert "memory_id" in data
        assert data["memory"] == "Local user likes Python and FastAPI for backend development."
        assert "programming" in data["topics"]
        assert "python" in data["topics"]
        assert "local" in data["topics"]
        assert data["user_id"] == test_user_id

    def test_get_memories_for_user(self, client: httpx.Client, test_user_id: str, agent_run_for_memory: dict):
        """Test GET /memories returns memories for specific user."""
        response = client.get(f"/memories?user_id={test_user_id}&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert "meta" in data
        assert len(data["data"]) >= 1

        # Verify all memories belong to the test user
        for memory in data["data"]:
            assert memory["user_id"] == test_user_id

    def test_get_memory_by_id(self, client: httpx.Client, created_memory_id: str, test_user_id: str):
        """Test GET /memories/{memory_id} returns full memory details."""
        response = client.get(f"/memories/{created_memory_id}?user_id={test_user_id}&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert data["memory_id"] == created_memory_id
        assert "memory" in data
        assert "topics" in data
        assert data["user_id"] == test_user_id
        assert "updated_at" in data
        assert "frontend" in data["topics"]
        assert "local" in data["topics"]

    def test_get_memory_topics_list(self, client: httpx.Client, agent_run_for_memory: dict):
        """Test GET /memory_topics returns list of all topics."""
        response = client.get(f"/memory_topics?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

        # Should contain topics from our created memories
        assert "programming" in data or len(data) >= 1

    def test_update_memory_content(self, client: httpx.Client, created_memory_id: str, test_user_id: str):
        """Test PATCH /memories/{memory_id} updates memory content and topics."""
        response = client.patch(
            f"/memories/{created_memory_id}?db_id={self.DB_ID}",
            json={
                "memory": "Updated: Local user now prefers Rust over TypeScript.",
                "topics": ["programming", "preferences", "rust", "updated", "local"],
                "user_id": test_user_id,
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert "updated" in data["topics"]
        assert "rust" in data["topics"]
        assert "Rust" in data["memory"]

    def test_get_user_memory_stats(self, client: httpx.Client, agent_run_for_memory: dict):
        """Test GET /user_memory_stats returns statistics."""
        response = client.get(f"/user_memory_stats?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert "meta" in data

        # Should have at least one user with memories
        if len(data["data"]) > 0:
            stat = data["data"][0]
            assert "user_id" in stat
            assert "total_memories" in stat
            assert stat["total_memories"] >= 1

    def test_delete_memory(self, client: httpx.Client, test_user_id: str):
        """Test DELETE /memories/{memory_id} removes the memory."""
        # Create a memory to delete
        create_response = client.post(
            "/memories?db_id=gateway-db",
            json={
                "memory": "Temporary local memory to be deleted.",
                "topics": ["temporary", "delete-test", "local"],
                "user_id": test_user_id,
            },
        )
        assert create_response.status_code == 200
        memory_id = create_response.json()["memory_id"]

        # Delete it
        response = client.delete(f"/memories/{memory_id}?user_id={test_user_id}&db_id={self.DB_ID}")
        assert response.status_code == 204

        # Verify it's gone
        verify_response = client.get(f"/memories/{memory_id}?user_id={test_user_id}&db_id={self.DB_ID}")
        assert verify_response.status_code == 404


class TestMemoryRoutesWithRemoteAgent:
    """Test memory routes with remote agent (assistant-agent)."""

    AGENT_ID = "assistant-agent"
    DB_ID = "remote-db"

    @pytest.fixture(scope="class")
    def agent_run_for_memory(self, client: httpx.Client, test_user_id: str) -> dict:
        """Run the remote agent to potentially generate memories."""
        session_id = str(uuid.uuid4())
        response = client.post(
            f"/agents/{self.AGENT_ID}/runs",
            data={
                "message": "My favorite color is blue and I like async programming.",
                "stream": "false",
                "session_id": session_id,
                "user_id": test_user_id,
            },
        )
        assert response.status_code == 200
        return {
            "session_id": session_id,
            "user_id": test_user_id,
            "agent_id": self.AGENT_ID,
        }

    @pytest.fixture(scope="class")
    def created_memory_id(self, client: httpx.Client, test_user_id: str) -> str:
        """Create a memory for testing CRUD operations with remote agent user."""
        response = client.post(
            f"/memories?db_id={self.DB_ID}",
            json={
                "memory": "Remote user prefers Go over Python for systems programming.",
                "topics": ["programming", "preferences", "systems", "remote"],
                "user_id": test_user_id,
            },
        )
        assert response.status_code == 200
        return response.json()["memory_id"]

    def test_create_memory_for_remote_agent_user(
        self, client: httpx.Client, test_user_id: str, agent_run_for_memory: dict
    ):
        """Test POST /memories creates memory for user who interacted with remote agent."""
        response = client.post(
            f"/memories?db_id={self.DB_ID}",
            json={
                "memory": "Remote user likes Kubernetes and Docker for deployment.",
                "topics": ["devops", "containers", "kubernetes", "remote"],
                "user_id": test_user_id,
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert "memory_id" in data
        assert "Kubernetes" in data["memory"]
        assert "devops" in data["topics"]
        assert "remote" in data["topics"]
        assert data["user_id"] == test_user_id

    def test_get_memories_for_remote_user(self, client: httpx.Client, test_user_id: str, agent_run_for_memory: dict):
        """Test GET /memories returns memories for remote agent user."""
        response = client.get(f"/memories?user_id={test_user_id}&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert len(data["data"]) >= 1

        # Verify all memories belong to the test user
        for memory in data["data"]:
            assert memory["user_id"] == test_user_id

    def test_get_memory_by_id_for_remote_user(self, client: httpx.Client, created_memory_id: str, test_user_id: str):
        """Test GET /memories/{memory_id} returns memory for remote agent user."""
        response = client.get(f"/memories/{created_memory_id}?user_id={test_user_id}&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert data["memory_id"] == created_memory_id
        assert data["user_id"] == test_user_id
        assert "remote" in data["topics"]

    def test_update_memory_for_remote_user(self, client: httpx.Client, created_memory_id: str, test_user_id: str):
        """Test PATCH /memories/{memory_id} updates memory for remote agent user."""
        response = client.patch(
            f"/memories/{created_memory_id}?db_id={self.DB_ID}",
            json={
                "memory": "Updated: Remote user now prefers Zig over Go.",
                "topics": ["programming", "preferences", "zig", "updated", "remote"],
                "user_id": test_user_id,
            },
        )
        assert response.status_code == 200
        data = response.json()

        assert "updated" in data["topics"]
        assert "zig" in data["topics"]
        assert "Zig" in data["memory"]

    def test_delete_memory_for_remote_user(self, client: httpx.Client, test_user_id: str):
        """Test DELETE /memories/{memory_id} removes memory for remote agent user."""
        # Create a memory to delete
        create_response = client.post(
            f"/memories?db_id={self.DB_ID}",
            json={
                "memory": "Temporary remote memory to be deleted.",
                "topics": ["temporary", "delete-test", "remote"],
                "user_id": test_user_id,
            },
        )
        assert create_response.status_code == 200
        memory_id = create_response.json()["memory_id"]

        # Delete it
        response = client.delete(f"/memories/{memory_id}?user_id={test_user_id}&db_id=gateway-db")
        assert response.status_code == 204

        # Verify it's gone
        verify_response = client.get(f"/memories/{memory_id}?user_id={test_user_id}&db_id=gateway-db")
        assert verify_response.status_code == 404
