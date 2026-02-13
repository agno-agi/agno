"""
System Tests for AgentOS Evals Routes.

Run with: pytest test_evals_routes.py -v --tb=short
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
# Eval Routes Tests
# =============================================================================


class TestLocalEvalRoutes:
    """Test eval routes with local agent (gateway-agent)."""

    AGENT_ID = "gateway-agent"
    DB_ID = "gateway-db"

    @pytest.fixture(scope="class")
    def created_eval_run(self, client: httpx.Client) -> dict:
        """Create an accuracy eval run for testing CRUD operations."""
        response = client.post(
            f"/eval-runs?db_id={self.DB_ID}",
            json={
                "agent_id": self.AGENT_ID,
                "eval_type": "accuracy",
                "input": "What is the capital of France?",
                "expected_output": "Paris",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert data["eval_type"] == "accuracy"
        assert data["agent_id"] == self.AGENT_ID
        return data

    def test_get_eval_runs_paginated(self, client: httpx.Client, created_eval_run: dict):
        """Test GET /eval-runs returns paginated evaluation runs including created eval."""
        response = client.get(f"/eval-runs?limit=10&page=1&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert "meta" in data
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 1

        # Verify our created eval is in the list
        eval_ids = [e["id"] for e in data["data"]]
        assert created_eval_run["id"] in eval_ids

        meta = data["meta"]
        assert "page" in meta
        assert "limit" in meta
        assert "total_count" in meta

    def test_get_eval_runs_filtered_by_local_agent(self, client: httpx.Client, created_eval_run: dict):
        """Test GET /eval-runs filters by local agent_id."""
        response = client.get(f"/eval-runs?agent_id={self.AGENT_ID}&limit=10&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert len(data["data"]) >= 1

        for eval_run in data["data"]:
            assert eval_run["agent_id"] == self.AGENT_ID

        # Verify our created eval is in the filtered results
        eval_ids = [e["id"] for e in data["data"]]
        assert created_eval_run["id"] in eval_ids

    def test_get_eval_run_by_id(self, client: httpx.Client, created_eval_run: dict):
        """Test GET /eval-runs/{eval_run_id} returns the specific eval run."""
        eval_id = created_eval_run["id"]
        response = client.get(f"/eval-runs/{eval_id}?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert data["id"] == eval_id
        assert data["agent_id"] == self.AGENT_ID
        assert data["eval_type"] == "accuracy"
        assert "eval_data" in data
        assert "created_at" in data

    def test_update_eval_run_name(self, client: httpx.Client, created_eval_run: dict):
        """Test PATCH /eval-runs/{eval_run_id} updates the eval run name."""
        eval_id = created_eval_run["id"]
        new_name = f"Updated Local Eval {uuid.uuid4().hex[:8]}"

        response = client.patch(
            f"/eval-runs/{eval_id}?db_id={self.DB_ID}",
            json={"name": new_name},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["id"] == eval_id
        assert data["name"] == new_name

        # Verify the update persisted
        verify_response = client.get(f"/eval-runs/{eval_id}?db_id={self.DB_ID}")
        assert verify_response.status_code == 200
        assert verify_response.json()["name"] == new_name

    def test_delete_eval_run(self, client: httpx.Client):
        """Test DELETE /eval-runs removes the eval run."""
        # Create an eval to delete
        create_response = client.post(
            f"/eval-runs?db_id={self.DB_ID}",
            json={
                "agent_id": self.AGENT_ID,
                "eval_type": "accuracy",
                "input": "What is 2 + 2?",
                "expected_output": "4",
            },
        )
        assert create_response.status_code == 200
        eval_id = create_response.json()["id"]

        # Delete it
        response = client.request(
            "DELETE",
            f"/eval-runs?db_id={self.DB_ID}",
            json={"eval_run_ids": [eval_id]},
        )
        assert response.status_code == 204

        # Verify it's gone
        verify_response = client.get(f"/eval-runs/{eval_id}?db_id={self.DB_ID}")
        assert verify_response.status_code == 404


class TestRemoteEvalRoutes:
    """Test eval routes with remote agent (assistant-agent)."""

    AGENT_ID = "assistant-agent"
    DB_ID = "remote-db"

    @pytest.fixture(scope="class")
    def created_eval_run(self, client: httpx.Client) -> dict:
        """Create an accuracy eval run for testing CRUD operations."""
        response = client.post(
            f"/eval-runs?db_id={self.DB_ID}",
            json={
                "agent_id": self.AGENT_ID,
                "eval_type": "accuracy",
                "input": "What is the capital of Germany?",
                "expected_output": "Berlin",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert data["eval_type"] == "accuracy"
        assert data["agent_id"] == self.AGENT_ID
        return data

    def test_get_eval_runs_paginated(self, client: httpx.Client, created_eval_run: dict):
        """Test GET /eval-runs returns paginated evaluation runs including created eval."""
        response = client.get(f"/eval-runs?limit=10&page=1&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert "meta" in data
        assert isinstance(data["data"], list)
        assert len(data["data"]) >= 1

        # Verify our created eval is in the list
        eval_ids = [e["id"] for e in data["data"]]
        assert created_eval_run["id"] in eval_ids

        meta = data["meta"]
        assert "page" in meta
        assert "limit" in meta
        assert "total_count" in meta

    def test_get_eval_runs_filtered_by_remote_agent(self, client: httpx.Client, created_eval_run: dict):
        """Test GET /eval-runs filters by remote agent_id."""
        response = client.get(f"/eval-runs?agent_id={self.AGENT_ID}&limit=10&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "data" in data
        assert len(data["data"]) >= 1

        for eval_run in data["data"]:
            assert eval_run["agent_id"] == self.AGENT_ID

        # Verify our created eval is in the filtered results
        eval_ids = [e["id"] for e in data["data"]]
        assert created_eval_run["id"] in eval_ids

    def test_get_eval_run_by_id(self, client: httpx.Client, created_eval_run: dict):
        """Test GET /eval-runs/{eval_run_id} returns the specific eval run."""
        eval_id = created_eval_run["id"]
        response = client.get(f"/eval-runs/{eval_id}?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert data["id"] == eval_id
        assert data["agent_id"] == self.AGENT_ID
        assert data["eval_type"] == "accuracy"
        assert "eval_data" in data
        assert "created_at" in data

    def test_update_eval_run_name(self, client: httpx.Client, created_eval_run: dict):
        """Test PATCH /eval-runs/{eval_run_id} updates the eval run name."""
        eval_id = created_eval_run["id"]
        new_name = f"Updated Remote Eval {uuid.uuid4().hex[:8]}"

        response = client.patch(
            f"/eval-runs/{eval_id}?db_id={self.DB_ID}",
            json={"name": new_name},
        )
        assert response.status_code == 200
        data = response.json()

        assert data["id"] == eval_id
        assert data["name"] == new_name

        # Verify the update persisted
        verify_response = client.get(f"/eval-runs/{eval_id}?db_id={self.DB_ID}")
        assert verify_response.status_code == 200
        assert verify_response.json()["name"] == new_name

    def test_delete_eval_run(self, client: httpx.Client):
        """Test DELETE /eval-runs removes the eval run."""
        # Create an eval to delete
        create_response = client.post(
            f"/eval-runs?db_id={self.DB_ID}",
            json={
                "agent_id": self.AGENT_ID,
                "eval_type": "accuracy",
                "input": "What is 3 + 3?",
                "expected_output": "6",
            },
        )
        assert create_response.status_code == 200
        eval_id = create_response.json()["id"]

        # Delete it
        response = client.request(
            "DELETE",
            f"/eval-runs?db_id={self.DB_ID}",
            json={"eval_run_ids": [eval_id]},
        )
        assert response.status_code == 204

        # Verify it's gone
        verify_response = client.get(f"/eval-runs/{eval_id}?db_id={self.DB_ID}")
        assert verify_response.status_code == 404
