"""
Unit tests for the Components router.

Tests cover:
- GET /components - List components
- POST /components - Create component
- GET /components/{component_id} - Get component
- PATCH /components/{component_id} - Update component
- DELETE /components/{component_id} - Delete component
- GET /components/{component_id}/configs - List configs
- POST /components/{component_id}/configs - Create config
- GET /components/{component_id}/configs/current - Get current config
- GET /components/{component_id}/configs/{version} - Get config version
- PATCH /components/{component_id}/configs/{version} - Update config
- DELETE /components/{component_id}/configs/{version} - Delete config
- POST /components/{component_id}/configs/{version}/set-current - Set current version
"""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.base import BaseDb, ComponentType
from agno.os.routers.components import get_components_router
from agno.os.settings import AgnoAPISettings

# =============================================================================
# Fixtures
# =============================================================================


def _create_mock_db_class():
    """Create a concrete BaseDb subclass with all abstract methods stubbed."""
    abstract_methods = {}
    for name in dir(BaseDb):
        attr = getattr(BaseDb, name, None)
        if getattr(attr, "__isabstractmethod__", False):
            abstract_methods[name] = MagicMock()
    return type("MockDb", (BaseDb,), abstract_methods)


@pytest.fixture
def mock_db():
    """Create a mock database instance."""
    MockDbClass = _create_mock_db_class()
    db = MockDbClass()
    db.id = "test-db"
    db.list_components = MagicMock()
    db.get_component = MagicMock()
    db.upsert_component = MagicMock()
    db.delete_component = MagicMock()
    db.create_component_with_config = MagicMock()
    db.list_configs = MagicMock()
    db.get_config = MagicMock()
    db.upsert_config = MagicMock()
    db.delete_config = MagicMock()
    db.set_current_version = MagicMock()
    db.to_dict = MagicMock(return_value={"type": "postgres", "id": "test-db"})
    return db


@pytest.fixture
def settings():
    """Create test settings with auth disabled (no security key = auth disabled)."""
    return AgnoAPISettings()


@pytest.fixture
def client(mock_db, settings):
    """Create a FastAPI test client with the components router."""
    app = FastAPI()
    router = get_components_router(os_db=mock_db, settings=settings)
    app.include_router(router)
    return TestClient(app)


# =============================================================================
# List Components Tests
# =============================================================================


class TestListComponents:
    """Tests for GET /components endpoint."""

    def test_list_components_returns_paginated_response(self, client, mock_db):
        """Test list_components returns paginated response."""
        mock_db.list_components.return_value = (
            [
                {"component_id": "agent-1", "name": "Agent 1", "component_type": "agent", "created_at": 1234567890},
                {"component_id": "agent-2", "name": "Agent 2", "component_type": "agent", "created_at": 1234567890},
            ],
            2,
        )

        response = client.get("/components")

        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 2
        assert data["meta"]["total_count"] == 2
        assert data["meta"]["page"] == 1

    def test_list_components_with_type_filter(self, client, mock_db):
        """Test list_components filters by component type."""
        mock_db.list_components.return_value = ([], 0)

        response = client.get("/components?component_type=agent")

        assert response.status_code == 200
        mock_db.list_components.assert_called_once()
        call_args = mock_db.list_components.call_args
        assert call_args.kwargs["component_type"] == ComponentType.AGENT

    def test_list_components_with_pagination(self, client, mock_db):
        """Test list_components with pagination parameters."""
        mock_db.list_components.return_value = ([], 100)

        response = client.get("/components?page=3&limit=10")

        assert response.status_code == 200
        mock_db.list_components.assert_called_once()
        call_args = mock_db.list_components.call_args
        assert call_args.kwargs["limit"] == 10
        assert call_args.kwargs["offset"] == 20  # (3-1) * 10

    def test_list_components_handles_error(self, client, mock_db):
        """Test list_components returns 500 on error."""
        mock_db.list_components.side_effect = Exception("DB error")

        response = client.get("/components")

        assert response.status_code == 500


# =============================================================================
# Create Component Tests
# =============================================================================


class TestCreateComponent:
    """Tests for POST /components endpoint."""

    def test_create_component_success(self, client, mock_db):
        """Test create_component creates a new component."""
        mock_db.create_component_with_config.return_value = (
            {
                "component_id": "test-agent",
                "name": "Test Agent",
                "component_type": "agent",
                "created_at": 1234567890,
            },
            {"version": 1},
        )

        response = client.post(
            "/components",
            json={
                "name": "Test Agent",
                "component_type": "agent",
                "config": {"id": "test-agent"},
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["component_id"] == "test-agent"
        assert data["name"] == "Test Agent"

    def test_create_component_generates_id_from_name(self, client, mock_db):
        """Test create_component generates ID from name if not provided."""
        mock_db.create_component_with_config.return_value = (
            {"component_id": "my-agent", "name": "My Agent", "component_type": "agent", "created_at": 1234567890},
            {"version": 1},
        )

        response = client.post(
            "/components",
            json={"name": "My Agent", "component_type": "agent"},
        )

        assert response.status_code == 201
        # Verify that component_id was generated (checked in the call)
        call_args = mock_db.create_component_with_config.call_args
        assert call_args.kwargs["component_id"] == "my-agent"

    def test_create_component_with_explicit_id(self, client, mock_db):
        """Test create_component uses provided component_id."""
        mock_db.create_component_with_config.return_value = (
            {"component_id": "custom-id", "name": "Test", "component_type": "agent", "created_at": 1234567890},
            {"version": 1},
        )

        response = client.post(
            "/components",
            json={
                "name": "Test",
                "component_type": "agent",
                "component_id": "custom-id",
            },
        )

        assert response.status_code == 201
        call_args = mock_db.create_component_with_config.call_args
        assert call_args.kwargs["component_id"] == "custom-id"

    def test_create_component_handles_value_error(self, client, mock_db):
        """Test create_component returns 400 on ValueError."""
        mock_db.create_component_with_config.side_effect = ValueError("Invalid config")

        response = client.post(
            "/components",
            json={"name": "Test", "component_type": "agent"},
        )

        assert response.status_code == 400


# =============================================================================
# Get Component Tests
# =============================================================================


class TestGetComponent:
    """Tests for GET /components/{component_id} endpoint."""

    def test_get_component_success(self, client, mock_db):
        """Test get_component returns component."""
        mock_db.get_component.return_value = {
            "component_id": "agent-1",
            "name": "Agent 1",
            "component_type": "agent",
            "created_at": 1234567890,
        }

        response = client.get("/components/agent-1")

        assert response.status_code == 200
        data = response.json()
        assert data["component_id"] == "agent-1"

    def test_get_component_not_found(self, client, mock_db):
        """Test get_component returns 404 when not found."""
        mock_db.get_component.return_value = None

        response = client.get("/components/nonexistent")

        assert response.status_code == 404


# =============================================================================
# Update Component Tests
# =============================================================================


class TestUpdateComponent:
    """Tests for PATCH /components/{component_id} endpoint."""

    def test_update_component_success(self, client, mock_db):
        """Test update_component updates component."""
        mock_db.get_component.return_value = {
            "component_id": "agent-1",
            "name": "Old Name",
            "component_type": "agent",
            "created_at": 1234567890,
        }
        mock_db.upsert_component.return_value = {
            "component_id": "agent-1",
            "name": "New Name",
            "component_type": "agent",
            "created_at": 1234567890,
        }

        response = client.patch("/components/agent-1", json={"name": "New Name"})

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "New Name"

    def test_update_component_not_found(self, client, mock_db):
        """Test update_component returns 404 when not found."""
        mock_db.get_component.return_value = None

        response = client.patch("/components/nonexistent", json={"name": "New Name"})

        assert response.status_code == 404


# =============================================================================
# Delete Component Tests
# =============================================================================


class TestDeleteComponent:
    """Tests for DELETE /components/{component_id} endpoint."""

    def test_delete_component_success(self, client, mock_db):
        """Test delete_component deletes component."""
        mock_db.delete_component.return_value = True

        response = client.delete("/components/agent-1")

        assert response.status_code == 204

    def test_delete_component_not_found(self, client, mock_db):
        """Test delete_component returns 404 when not found."""
        mock_db.delete_component.return_value = False

        response = client.delete("/components/nonexistent")

        assert response.status_code == 404


# =============================================================================
# List Configs Tests
# =============================================================================


class TestListConfigs:
    """Tests for GET /components/{component_id}/configs endpoint."""

    def test_list_configs_success(self, client, mock_db):
        """Test list_configs returns list of configs."""
        mock_db.list_configs.return_value = [
            {"component_id": "agent-1", "version": 1, "stage": "draft", "config": {}, "created_at": 1234567890},
            {"component_id": "agent-1", "version": 2, "stage": "published", "config": {}, "created_at": 1234567890},
        ]

        response = client.get("/components/agent-1/configs")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_list_configs_with_include_config(self, client, mock_db):
        """Test list_configs passes include_config parameter."""
        mock_db.list_configs.return_value = []

        response = client.get("/components/agent-1/configs?include_config=false")

        assert response.status_code == 200
        mock_db.list_configs.assert_called_once_with("agent-1", include_config=False)


# =============================================================================
# Create Config Tests
# =============================================================================


class TestCreateConfig:
    """Tests for POST /components/{component_id}/configs endpoint."""

    def test_create_config_success(self, client, mock_db):
        """Test create_config creates new config version."""
        mock_db.upsert_config.return_value = {
            "component_id": "agent-1",
            "version": 1,
            "config": {"name": "Agent"},
            "stage": "draft",
            "created_at": 1234567890,
        }

        response = client.post(
            "/components/agent-1/configs",
            json={"config": {"name": "Agent"}, "stage": "draft"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["version"] == 1

    def test_create_config_handles_value_error(self, client, mock_db):
        """Test create_config returns 400 on ValueError."""
        mock_db.upsert_config.side_effect = ValueError("Invalid config")

        response = client.post(
            "/components/agent-1/configs",
            json={"config": {}},
        )

        assert response.status_code == 400


# =============================================================================
# Get Current Config Tests
# =============================================================================


class TestGetCurrentConfig:
    """Tests for GET /components/{component_id}/configs/current endpoint."""

    def test_get_current_config_success(self, client, mock_db):
        """Test get_current_config returns current config."""
        mock_db.get_config.return_value = {
            "component_id": "agent-1",
            "version": 2,
            "config": {"name": "Agent"},
            "stage": "published",
            "created_at": 1234567890,
        }

        response = client.get("/components/agent-1/configs/current")

        assert response.status_code == 200
        data = response.json()
        assert data["version"] == 2

    def test_get_current_config_not_found(self, client, mock_db):
        """Test get_current_config returns 404 when no current config."""
        mock_db.get_config.return_value = None

        response = client.get("/components/agent-1/configs/current")

        assert response.status_code == 404


# =============================================================================
# Get Config Version Tests
# =============================================================================


class TestGetConfigVersion:
    """Tests for GET /components/{component_id}/configs/{version} endpoint."""

    def test_get_config_version_success(self, client, mock_db):
        """Test get_config_version returns specific version."""
        mock_db.get_config.return_value = {
            "component_id": "agent-1",
            "version": 3,
            "config": {"name": "Agent v3"},
            "stage": "published",
            "created_at": 1234567890,
        }

        response = client.get("/components/agent-1/configs/3")

        assert response.status_code == 200
        data = response.json()
        assert data["version"] == 3

    def test_get_config_version_not_found(self, client, mock_db):
        """Test get_config_version returns 404 when version not found."""
        mock_db.get_config.return_value = None

        response = client.get("/components/agent-1/configs/999")

        assert response.status_code == 404


# =============================================================================
# Update Config Tests
# =============================================================================


class TestUpdateConfig:
    """Tests for PATCH /components/{component_id}/configs/{version} endpoint."""

    def test_update_config_success(self, client, mock_db):
        """Test update_config updates config version."""
        mock_db.upsert_config.return_value = {
            "component_id": "agent-1",
            "version": 1,
            "config": {"name": "Updated Agent"},
            "stage": "draft",
            "created_at": 1234567890,
        }

        response = client.patch(
            "/components/agent-1/configs/1",
            json={"config": {"name": "Updated Agent"}},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["config"]["name"] == "Updated Agent"

    def test_update_config_handles_value_error(self, client, mock_db):
        """Test update_config returns 400 on ValueError."""
        mock_db.upsert_config.side_effect = ValueError("Cannot update published config")

        response = client.patch(
            "/components/agent-1/configs/1",
            json={"stage": "published"},
        )

        assert response.status_code == 400


# =============================================================================
# Delete Config Tests
# =============================================================================


class TestDeleteConfig:
    """Tests for DELETE /components/{component_id}/configs/{version} endpoint."""

    def test_delete_config_success(self, client, mock_db):
        """Test delete_config deletes config version."""
        mock_db.delete_config.return_value = True

        response = client.delete("/components/agent-1/configs/1")

        assert response.status_code == 204

    def test_delete_config_not_found(self, client, mock_db):
        """Test delete_config returns 404 when not found."""
        mock_db.delete_config.return_value = False

        response = client.delete("/components/agent-1/configs/999")

        assert response.status_code == 404

    def test_delete_config_handles_value_error(self, client, mock_db):
        """Test delete_config returns 400 on ValueError."""
        mock_db.delete_config.side_effect = ValueError("Cannot delete current config")

        response = client.delete("/components/agent-1/configs/1")

        assert response.status_code == 400


# =============================================================================
# Set Current Config Tests
# =============================================================================


class TestSetCurrentConfig:
    """Tests for POST /components/{component_id}/configs/{version}/set-current endpoint."""

    def test_set_current_config_success(self, client, mock_db):
        """Test set_current_config sets version as current."""
        mock_db.set_current_version.return_value = True
        mock_db.get_component.return_value = {
            "component_id": "agent-1",
            "name": "Agent 1",
            "component_type": "agent",
            "current_version": 3,
            "created_at": 1234567890,
        }

        response = client.post("/components/agent-1/configs/3/set-current")

        assert response.status_code == 200
        data = response.json()
        assert data["current_version"] == 3

    def test_set_current_config_not_found(self, client, mock_db):
        """Test set_current_config returns 404 when version not found."""
        mock_db.set_current_version.return_value = False

        response = client.post("/components/agent-1/configs/999/set-current")

        assert response.status_code == 404

    def test_set_current_config_handles_value_error(self, client, mock_db):
        """Test set_current_config returns 400 on ValueError."""
        mock_db.set_current_version.side_effect = ValueError("Version not published")

        response = client.post("/components/agent-1/configs/1/set-current")

        assert response.status_code == 400
