"""
System Tests for AgentOS Metrics Routes.

Run with: pytest test_metrics_routes.py -v --tb=short
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
# Metrics Routes Tests
# =============================================================================


class TestLocalMetricsRoutes:
    """Test metrics routes with local database (gateway-db)."""

    DB_ID = "gateway-db"
    AGENT_ID = "gateway-agent"

    @pytest.fixture(scope="class")
    def metrics_test_user_id(self) -> str:
        """Generate a unique user ID for metrics tests."""
        return f"metrics-local-user-{uuid.uuid4().hex[:8]}"

    @pytest.fixture(scope="class")
    def generate_metrics_data(self, client: httpx.Client, metrics_test_user_id: str) -> dict:
        """Run an agent to generate some metrics data."""
        session_id = str(uuid.uuid4())
        response = client.post(
            f"/agents/{self.AGENT_ID}/runs",
            data={
                "message": "Hello, generate some metrics data.",
                "stream": "false",
                "session_id": session_id,
                "user_id": metrics_test_user_id,
            },
        )
        assert response.status_code == 200
        return {
            "session_id": session_id,
            "user_id": metrics_test_user_id,
            "agent_id": self.AGENT_ID,
        }

    def test_get_metrics_structure(self, client: httpx.Client, generate_metrics_data: dict):
        """Test GET /metrics returns proper metrics structure for local db."""
        response = client.get(f"/metrics?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "metrics" in data
        assert isinstance(data["metrics"], list)
        assert "updated_at" in data

    def test_get_metrics_with_date_range(self, client: httpx.Client, generate_metrics_data: dict):
        """Test GET /metrics filters by date range for local db."""
        response = client.get(f"/metrics?starting_date=2024-01-01&ending_date=2030-12-31&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "metrics" in data
        assert isinstance(data["metrics"], list)

    def test_get_metrics_contains_expected_fields(self, client: httpx.Client, generate_metrics_data: dict):
        """Test GET /metrics returns metrics with expected fields for local db."""
        response = client.get(f"/metrics?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        if len(data["metrics"]) > 0:
            metric = data["metrics"][0]
            assert "id" in metric
            assert "agent_runs_count" in metric
            assert "agent_sessions_count" in metric
            assert "team_runs_count" in metric
            assert "team_sessions_count" in metric
            assert "workflow_runs_count" in metric
            assert "workflow_sessions_count" in metric
            assert "users_count" in metric
            assert "token_metrics" in metric
            assert "model_metrics" in metric
            assert "date" in metric
            assert "created_at" in metric
            assert "updated_at" in metric

    def test_refresh_metrics_returns_list(self, client: httpx.Client, generate_metrics_data: dict):
        """Test POST /metrics/refresh recalculates and returns metrics for local db."""
        response = client.post(f"/metrics/refresh?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert isinstance(data, list)

    def test_refresh_metrics_contains_expected_fields(self, client: httpx.Client, generate_metrics_data: dict):
        """Test POST /metrics/refresh returns metrics with expected fields for local db."""
        response = client.post(f"/metrics/refresh?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        if len(data) > 0:
            metric = data[0]
            assert "id" in metric
            assert "agent_runs_count" in metric
            assert "token_metrics" in metric
            assert "model_metrics" in metric
            assert "date" in metric


class TestRemoteMetricsRoutes:
    """Test metrics routes with remote database (remote-db)."""

    DB_ID = "remote-db"
    AGENT_ID = "assistant-agent"

    @pytest.fixture(scope="class")
    def metrics_test_user_id(self) -> str:
        """Generate a unique user ID for metrics tests."""
        return f"metrics-remote-user-{uuid.uuid4().hex[:8]}"

    @pytest.fixture(scope="class")
    def generate_metrics_data(self, client: httpx.Client, metrics_test_user_id: str) -> dict:
        """Run a remote agent to generate some metrics data."""
        session_id = str(uuid.uuid4())
        response = client.post(
            f"/agents/{self.AGENT_ID}/runs",
            data={
                "message": "Hello!",
                "stream": "false",
                "session_id": session_id,
                "user_id": metrics_test_user_id,
            },
        )
        assert response.status_code == 200
        return {
            "session_id": session_id,
            "user_id": metrics_test_user_id,
            "agent_id": self.AGENT_ID,
        }

    def test_get_metrics_structure(self, client: httpx.Client, generate_metrics_data: dict):
        """Test GET /metrics returns proper metrics structure for remote db."""
        response = client.get(f"/metrics?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "metrics" in data
        assert isinstance(data["metrics"], list)
        assert "updated_at" in data

    def test_get_metrics_with_date_range(self, client: httpx.Client, generate_metrics_data: dict):
        """Test GET /metrics filters by date range for remote db."""
        response = client.get(f"/metrics?starting_date=2024-01-01&ending_date=2030-12-31&db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert "metrics" in data
        assert isinstance(data["metrics"], list)

    def test_get_metrics_contains_expected_fields(self, client: httpx.Client, generate_metrics_data: dict):
        """Test GET /metrics returns metrics with expected fields for remote db."""
        response = client.get(f"/metrics?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        if len(data["metrics"]) > 0:
            metric = data["metrics"][0]
            assert "id" in metric
            assert "agent_runs_count" in metric
            assert "agent_sessions_count" in metric
            assert "team_runs_count" in metric
            assert "team_sessions_count" in metric
            assert "workflow_runs_count" in metric
            assert "workflow_sessions_count" in metric
            assert "users_count" in metric
            assert "token_metrics" in metric
            assert "model_metrics" in metric
            assert "date" in metric
            assert "created_at" in metric
            assert "updated_at" in metric

    def test_refresh_metrics_returns_list(self, client: httpx.Client, generate_metrics_data: dict):
        """Test POST /metrics/refresh recalculates and returns metrics for remote db."""
        response = client.post(f"/metrics/refresh?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        assert isinstance(data, list)

    def test_refresh_metrics_contains_expected_fields(self, client: httpx.Client, generate_metrics_data: dict):
        """Test POST /metrics/refresh returns metrics with expected fields for remote db."""
        response = client.post(f"/metrics/refresh?db_id={self.DB_ID}")
        assert response.status_code == 200
        data = response.json()

        if len(data) > 0:
            metric = data[0]
            assert "id" in metric
            assert "agent_runs_count" in metric
            assert "token_metrics" in metric
            assert "model_metrics" in metric
            assert "date" in metric
