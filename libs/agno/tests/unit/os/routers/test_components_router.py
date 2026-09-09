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
- POST /components/{component_id}/restore - Restore archived component
- Optional guard bodies (compare-and-set) and typed catalog error mappings
"""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.db.base import (
    BaseDb,
    ComponentArchivedError,
    ComponentDependencyError,
    ComponentDraftRequiredError,
    ComponentType,
    ComponentVersionConflictError,
)
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
    db.restore_component = MagicMock()
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

    def test_create_team_persists_links_for_db_members(self, client, mock_db):
        """Test create_component builds component links for DB-persisted members."""
        mock_db.get_component.return_value = {"component_id": "member-agent", "current_version": 3}
        mock_db.create_component_with_config.return_value = (
            {"component_id": "my-team", "name": "My Team", "component_type": "team", "created_at": 1},
            {"version": 1},
        )

        response = client.post(
            "/components",
            json={
                "name": "My Team",
                "component_type": "team",
                "component_id": "my-team",
                "config": {"id": "my-team", "members": [{"type": "agent", "agent_id": "member-agent"}]},
            },
        )

        assert response.status_code == 201
        links = mock_db.create_component_with_config.call_args.kwargs["links"]
        assert links == [
            {
                "link_kind": "member",
                "link_key": "member_0",
                "child_component_id": "member-agent",
                "child_version": 3,
                "position": 0,
                "meta": {"type": "agent"},
            }
        ]

    def test_create_team_with_registry_member_succeeds_without_link(self, mock_db, settings):
        """Test create_component allows a code-defined (registry) member with no link."""
        from agno.agent.agent import Agent
        from agno.registry import Registry

        # Not a DB component, but registered with the AgentOS instance
        mock_db.get_component.return_value = None
        mock_db.create_component_with_config.return_value = (
            {"component_id": "my-team", "name": "My Team", "component_type": "team", "created_at": 1},
            {"version": 1},
        )
        registry = Registry(agents=[Agent(id="member-agent", name="Member Agent")])

        app = FastAPI()
        app.include_router(get_components_router(os_db=mock_db, settings=settings, registry=registry))
        client = TestClient(app)

        response = client.post(
            "/components",
            json={
                "name": "My Team",
                "component_type": "team",
                "component_id": "my-team",
                "config": {"id": "my-team", "members": [{"type": "agent", "agent_id": "member-agent"}]},
            },
        )

        assert response.status_code == 201
        assert mock_db.create_component_with_config.call_args.kwargs["links"] is None

    def test_create_team_with_unresolved_member_returns_400(self, mock_db, settings):
        """Test create_component surfaces members that resolve to neither db nor registry."""
        from agno.registry import Registry

        mock_db.get_component.return_value = None
        registry = Registry(agents=[])

        app = FastAPI()
        app.include_router(get_components_router(os_db=mock_db, settings=settings, registry=registry))
        client = TestClient(app)

        response = client.post(
            "/components",
            json={
                "name": "My Team",
                "component_type": "team",
                "component_id": "my-team",
                "config": {"id": "my-team", "members": [{"type": "agent", "agent_id": "ghost-agent"}]},
            },
        )

        assert response.status_code == 400
        assert "ghost-agent" in response.json()["detail"]
        mock_db.create_component_with_config.assert_not_called()


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
# Update Component Current-Version Pointer Tests
# =============================================================================


class TestUpdateComponentCurrentVersionRouting:
    """PATCH current_version must route through set_current_version.

    upsert_component writes the pointer blindly; only set_current_version
    enforces the published-only dispatch invariant (draft and tombstoned
    targets refused) and the CAS guard atomically.
    """

    _component = {
        "component_id": "agent-1",
        "name": "Agent 1",
        "component_type": "agent",
        "current_version": 1,
        "created_at": 1234567890,
    }

    def test_patch_current_version_goes_through_set_current_version(self, client, mock_db):
        """The pointer move is delegated; upsert never receives the pointer."""
        mock_db.get_component.return_value = dict(self._component)
        mock_db.set_current_version.return_value = True
        mock_db.upsert_component.return_value = {**self._component, "current_version": 2}

        response = client.patch("/components/agent-1", json={"current_version": 2})

        assert response.status_code == 200
        assert response.json()["current_version"] == 2
        mock_db.set_current_version.assert_called_once_with(
            "agent-1", version=2, expected_current_version=None, user_id=None
        )
        assert "current_version" not in mock_db.upsert_component.call_args.kwargs

    def test_patch_current_version_to_invalid_stage_returns_400(self, client, mock_db):
        """A draft or tombstoned target (adapter ValueError) maps to 400."""
        mock_db.get_component.return_value = dict(self._component)
        mock_db.set_current_version.side_effect = ValueError(
            "Cannot set draft config agent-1 v2 as current. Only published configs can be current."
        )

        response = client.patch("/components/agent-1", json={"current_version": 2})

        assert response.status_code == 400
        mock_db.upsert_component.assert_not_called()

    def test_patch_current_version_to_nonexistent_returns_404(self, client, mock_db):
        """A version the adapter cannot find (returns False) maps to 404."""
        mock_db.get_component.return_value = dict(self._component)
        mock_db.set_current_version.return_value = False

        response = client.patch("/components/agent-1", json={"current_version": 99})

        assert response.status_code == 404
        mock_db.upsert_component.assert_not_called()

    def test_patch_current_version_threads_the_guard(self, client, mock_db):
        """guard.current_version becomes the CAS kwarg on set_current_version."""
        mock_db.get_component.return_value = dict(self._component)
        mock_db.set_current_version.return_value = True
        mock_db.upsert_component.return_value = {**self._component, "current_version": 2}

        response = client.patch(
            "/components/agent-1",
            json={"current_version": 2, "guard": {"current_version": 1}},
        )

        assert response.status_code == 200
        assert mock_db.set_current_version.call_args.kwargs["expected_current_version"] == 1

    def test_patch_current_version_conflict_returns_409(self, client, mock_db):
        """A CAS race inside set_current_version surfaces as 409."""
        mock_db.get_component.return_value = dict(self._component)
        mock_db.set_current_version.side_effect = ComponentVersionConflictError(
            "Component agent-1 current version is 3, expected 1"
        )

        response = client.patch(
            "/components/agent-1",
            json={"current_version": 2, "guard": {"current_version": 1}},
        )

        assert response.status_code == 409
        mock_db.upsert_component.assert_not_called()


class TestUpdateComponentCurrentVersionEndToEnd:
    """The published-only dispatch invariant, pinned over a real SqliteDb."""

    @pytest.fixture
    def real_db(self, tmp_path):
        from agno.db.sqlite import SqliteDb

        db = SqliteDb(id="router-pointer-db", db_file=str(tmp_path / "router-pointer.db"))
        db.create_component_with_config(
            component_id="agent-1",
            component_type=ComponentType.AGENT,
            name="agent-1",
            config={"name": "agent-1"},
            stage="published",
        )  # v1 published, current = 1
        db.upsert_config("agent-1", config={"name": "v2-draft"})  # v2 draft
        db.upsert_config("agent-1", config={"name": "v3"}, stage="published")  # v3 published, current = 3
        db.upsert_config("agent-1", config={"name": "v4"})  # v4 draft
        db.delete_config("agent-1", 4)  # v4 tombstoned
        return db

    @pytest.fixture
    def real_client(self, real_db, settings):
        app = FastAPI()
        app.include_router(get_components_router(os_db=real_db, settings=settings))
        return TestClient(app)

    def test_patch_to_a_draft_returns_400_and_pointer_stays(self, real_client, real_db):
        response = real_client.patch("/components/agent-1", json={"current_version": 2})
        assert response.status_code == 400
        assert real_db.get_component("agent-1")["current_version"] == 3

    def test_patch_to_a_tombstone_returns_400_and_pointer_stays(self, real_client, real_db):
        response = real_client.patch("/components/agent-1", json={"current_version": 4})
        assert response.status_code == 400
        assert real_db.get_component("agent-1")["current_version"] == 3

    def test_patch_to_a_nonexistent_version_returns_404_and_pointer_stays(self, real_client, real_db):
        response = real_client.patch("/components/agent-1", json={"current_version": 99})
        assert response.status_code == 404
        assert real_db.get_component("agent-1")["current_version"] == 3

    def test_patch_to_a_published_version_moves_the_pointer(self, real_client, real_db):
        response = real_client.patch("/components/agent-1", json={"current_version": 1})
        assert response.status_code == 200
        assert response.json()["current_version"] == 1
        assert real_db.get_component("agent-1")["current_version"] == 1
        # Dispatch reads follow the pointer to the published payload
        current = real_db.get_current_config("agent-1")
        assert current is not None and current["version"] == 1 and current["stage"] == "published"

    def test_patch_pointer_and_fields_together(self, real_client, real_db):
        """The UI can move the pointer and rename in one PATCH."""
        response = real_client.patch(
            "/components/agent-1",
            json={"current_version": 1, "name": "Renamed", "guard": {"current_version": 3}},
        )
        assert response.status_code == 200
        row = real_db.get_component("agent-1")
        assert row["current_version"] == 1 and row["name"] == "Renamed"

    def test_patch_with_bogus_component_type_is_400_and_pointer_stays(self, real_client, real_db):
        """A6: the PATCH is atomic. Body validation runs BEFORE the pointer
        write, so a bad component_type 400s with the pointer untouched -
        it must never 400 AFTER the pointer move already committed."""
        response = real_client.patch(
            "/components/agent-1",
            json={"current_version": 1, "component_type": "bogus"},
        )
        assert response.status_code == 400
        row = real_db.get_component("agent-1")
        assert row["current_version"] == 3
        assert row["component_type"] == "agent"

    def test_patch_with_bogus_component_type_and_guard_is_400_and_pointer_stays(self, real_client, real_db):
        """Same atomicity with the CAS guard present: the 400 wins before any write."""
        response = real_client.patch(
            "/components/agent-1",
            json={"current_version": 1, "component_type": "bogus", "guard": {"current_version": 3}},
        )
        assert response.status_code == 400
        assert real_db.get_component("agent-1")["current_version"] == 3


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

    def test_delete_component_delegates_the_cascade_to_the_adapter(self, client, mock_db):
        """Archiving via REST must run the same cascade every other archive surface runs.

        A schedule left pointing at an archived component only 404s on every tick,
        and retries - the exact failure the cascade exists to stop. The cascade now
        rides delete_component inside the archive's own transaction, so the route
        must not run its own: doing so would disable twice, and a caller-side
        cascade is precisely what let the SDK deletes bypass it. The cascade itself
        is pinned in tests/unit/db/test_component_liveness_guards.py, which covers
        the REST, StudioTools, SDK and hard-delete surfaces together.
        """
        mock_db.get_component.return_value = {"component_id": "agent-1", "component_type": "agent", "user_id": "u1"}
        mock_db.delete_component.return_value = True
        mock_db.disable_schedules_for_target = MagicMock(return_value=2)

        response = client.delete("/components/agent-1")

        assert response.status_code == 204
        assert mock_db.delete_component.call_count == 1
        mock_db.disable_schedules_for_target.assert_not_called()

    def test_delete_component_does_not_cascade_when_the_delete_failed(self, client, mock_db):
        """Nothing was archived, so nothing may be disabled."""
        mock_db.get_component.return_value = {"component_id": "agent-1", "component_type": "agent", "user_id": "u1"}
        mock_db.delete_component.return_value = False
        mock_db.disable_schedules_for_target = MagicMock(return_value=0)

        response = client.delete("/components/agent-1")

        assert response.status_code == 404
        mock_db.disable_schedules_for_target.assert_not_called()

    def test_delete_component_survives_a_db_without_scheduler_support(self, client, mock_db):
        """The component is archived; a missing scheduler primitive is not an error."""
        mock_db.get_component.return_value = {"component_id": "agent-1", "component_type": "agent", "user_id": "u1"}
        mock_db.delete_component.return_value = True
        mock_db.disable_schedules_for_target = MagicMock(side_effect=NotImplementedError)

        response = client.delete("/components/agent-1")

        assert response.status_code == 204

    def test_delete_component_survives_a_failing_cascade(self, client, mock_db):
        """A failed cascade must not turn a successful archive into a 500."""
        mock_db.get_component.return_value = {"component_id": "agent-1", "component_type": "agent", "user_id": "u1"}
        mock_db.delete_component.return_value = True
        mock_db.disable_schedules_for_target = MagicMock(side_effect=RuntimeError("db down"))

        response = client.delete("/components/agent-1")

        assert response.status_code == 204


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


# =============================================================================
# Guard (compare-and-set) Tests
# =============================================================================


class TestComponentGuards:
    """Tests for the optional guard bodies and typed catalog error mappings."""

    _config_row = {
        "component_id": "agent-1",
        "version": 4,
        "config": {"name": "Agent"},
        "stage": "draft",
        "created_at": 1234567890,
    }

    def test_create_config_with_guard_threads_expected_latest_version(self, client, mock_db):
        """POST configs with a guard passes expected_latest_version to upsert_config."""
        mock_db.upsert_config.return_value = self._config_row

        response = client.post(
            "/components/agent-1/configs",
            json={"config": {"name": "Agent"}, "guard": {"latest_version": 3}},
        )

        assert response.status_code == 201
        assert mock_db.upsert_config.call_args.kwargs["expected_latest_version"] == 3

    def test_create_config_without_guard_passes_none(self, client, mock_db):
        """The pre-guard UI shape (stage, set_current, config) still works unguarded."""
        mock_db.upsert_config.return_value = self._config_row

        response = client.post(
            "/components/agent-1/configs",
            json={"config": {"name": "Agent"}, "stage": "draft", "set_current": True},
        )

        assert response.status_code == 201
        assert mock_db.upsert_config.call_args.kwargs["expected_latest_version"] is None

    def test_update_config_with_guard_threads_expected_latest_version(self, client, mock_db):
        """PATCH configs/{version} with a guard passes expected_latest_version."""
        mock_db.upsert_config.return_value = self._config_row

        response = client.patch(
            "/components/agent-1/configs/4",
            json={"config": {"name": "Agent"}, "guard": {"latest_version": 4}},
        )

        assert response.status_code == 200
        assert mock_db.upsert_config.call_args.kwargs["expected_latest_version"] == 4

    def test_update_config_without_guard_passes_none(self, client, mock_db):
        """PATCH configs/{version} without a guard stays last-writer-wins."""
        mock_db.upsert_config.return_value = self._config_row

        response = client.patch(
            "/components/agent-1/configs/4",
            json={"config": {"name": "Agent"}},
        )

        assert response.status_code == 200
        assert mock_db.upsert_config.call_args.kwargs["expected_latest_version"] is None

    def test_set_current_with_guard_threads_expected_current_version(self, client, mock_db):
        """set-current with a guard passes expected_current_version."""
        mock_db.set_current_version.return_value = True
        mock_db.get_component.return_value = {
            "component_id": "agent-1",
            "name": "Agent 1",
            "component_type": "agent",
            "current_version": 3,
            "created_at": 1234567890,
        }

        response = client.post(
            "/components/agent-1/configs/3/set-current",
            json={"guard": {"current_version": 2}},
        )

        assert response.status_code == 200
        assert mock_db.set_current_version.call_args.kwargs["expected_current_version"] == 2

    def test_set_current_empty_body_still_works(self, client, mock_db):
        """set-current with no body (the UI shape) skips the guard."""
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
        assert mock_db.set_current_version.call_args.kwargs["expected_current_version"] is None

    def test_update_component_guard_mismatch_returns_409(self, client, mock_db):
        """PATCH component with a stale guard.current_version is rejected before writing."""
        mock_db.get_component.return_value = {
            "component_id": "agent-1",
            "name": "Agent 1",
            "component_type": "agent",
            "current_version": 5,
            "created_at": 1234567890,
        }

        response = client.patch(
            "/components/agent-1",
            json={"name": "New Name", "guard": {"current_version": 2}},
        )

        assert response.status_code == 409
        mock_db.upsert_component.assert_not_called()

    def test_update_component_guard_zero_matches_an_unpublished_component(self, client, mock_db):
        """guard.current_version=0 expects no live version: on a component that
        has never been published it matches (NULL pointer) and the write lands."""
        component = {
            "component_id": "agent-1",
            "name": "Agent 1",
            "component_type": "agent",
            "current_version": None,
            "created_at": 1234567890,
        }
        mock_db.get_component.return_value = component
        mock_db.upsert_component.return_value = {**component, "name": "New Name"}

        response = client.patch(
            "/components/agent-1",
            json={"name": "New Name", "guard": {"current_version": 0}},
        )

        assert response.status_code == 200, response.text
        mock_db.upsert_component.assert_called_once()

    def test_update_component_guard_false_is_not_zero(self, client, mock_db):
        """JSON false coerces to int 0 in the guard model; it must not pass as
        the "no live version" sentinel."""
        mock_db.get_component.return_value = {
            "component_id": "agent-1",
            "name": "Agent 1",
            "component_type": "agent",
            "current_version": None,
            "created_at": 1234567890,
        }

        response = client.patch(
            "/components/agent-1",
            json={"name": "New Name", "guard": {"current_version": False}},
        )

        assert response.status_code == 422, response.text
        mock_db.upsert_component.assert_not_called()

    def test_update_component_guard_zero_conflicts_with_a_live_version(self, client, mock_db):
        mock_db.get_component.return_value = {
            "component_id": "agent-1",
            "name": "Agent 1",
            "component_type": "agent",
            "current_version": 1,
            "created_at": 1234567890,
        }

        response = client.patch(
            "/components/agent-1",
            json={"name": "New Name", "guard": {"current_version": 0}},
        )

        assert response.status_code == 409
        mock_db.upsert_component.assert_not_called()

    def test_update_component_guard_match_succeeds(self, client, mock_db):
        """PATCH component with a matching guard.current_version writes normally."""
        component = {
            "component_id": "agent-1",
            "name": "Agent 1",
            "component_type": "agent",
            "current_version": 5,
            "created_at": 1234567890,
        }
        mock_db.get_component.return_value = component
        mock_db.upsert_component.return_value = {**component, "name": "New Name"}

        response = client.patch(
            "/components/agent-1",
            json={"name": "New Name", "guard": {"current_version": 5}},
        )

        assert response.status_code == 200
        assert response.json()["name"] == "New Name"

    def test_create_config_version_conflict_returns_409(self, client, mock_db):
        """ComponentVersionConflictError maps to 409, not the generic 400."""
        mock_db.upsert_config.side_effect = ComponentVersionConflictError("version conflict")

        response = client.post("/components/agent-1/configs", json={"config": {}})

        assert response.status_code == 409
        assert response.json()["detail"] == "version conflict"

    def test_create_config_archived_returns_409(self, client, mock_db):
        """ComponentArchivedError maps to 409."""
        mock_db.upsert_config.side_effect = ComponentArchivedError("component is archived")

        response = client.post("/components/agent-1/configs", json={"config": {}})

        assert response.status_code == 409

    def test_create_config_draft_required_returns_400(self, client, mock_db):
        """ComponentDraftRequiredError maps to 400."""
        mock_db.upsert_config.side_effect = ComponentDraftRequiredError("draft required")

        response = client.post("/components/agent-1/configs", json={"config": {}})

        assert response.status_code == 400

    def test_delete_component_dependency_returns_409(self, client, mock_db):
        """DELETE component refused by dependents maps to 409 listing the parents."""
        mock_db.delete_component.side_effect = ComponentDependencyError("Cannot delete agent-1: referenced by team-1")

        response = client.delete("/components/agent-1")

        assert response.status_code == 409
        assert "team-1" in response.json()["detail"]

    def test_delete_component_forwards_expected_current_version_query(self, client, mock_db):
        """DELETE component forwards the optional expected_current_version query guard."""
        mock_db.delete_component.return_value = True

        response = client.delete("/components/agent-1?expected_current_version=3")

        assert response.status_code == 204
        assert mock_db.delete_component.call_args.kwargs["expected_current_version"] == 3

    def test_delete_component_without_query_guard_passes_none(self, client, mock_db):
        """DELETE component without the query guard stays unguarded."""
        mock_db.delete_component.return_value = True

        response = client.delete("/components/agent-1")

        assert response.status_code == 204
        assert mock_db.delete_component.call_args.kwargs["expected_current_version"] is None


# =============================================================================
# Restore Component Tests
# =============================================================================


class TestRestoreComponent:
    """Tests for POST /components/{component_id}/restore endpoint."""

    def test_restore_component_success(self, client, mock_db):
        """Restore returns the restored component."""
        mock_db.restore_component.return_value = True
        mock_db.get_component.return_value = {
            "component_id": "agent-1",
            "name": "Agent 1",
            "component_type": "agent",
            "current_version": 2,
            "created_at": 1234567890,
        }

        response = client.post("/components/agent-1/restore")

        assert response.status_code == 200
        data = response.json()
        assert data["component_id"] == "agent-1"
        assert data["current_version"] == 2
        assert mock_db.restore_component.call_args.kwargs["user_id"] is None

    def test_restore_component_not_found(self, client, mock_db):
        """Restore of a component that does not exist at all returns 404."""
        mock_db.restore_component.return_value = False
        mock_db.get_component.return_value = None

        response = client.post("/components/nonexistent/restore")

        assert response.status_code == 404

    def test_restore_component_not_archived_returns_409(self, client, mock_db):
        """Restore of a live (not archived) component returns 409."""
        mock_db.restore_component.return_value = False
        mock_db.get_component.return_value = {
            "component_id": "agent-1",
            "name": "Agent 1",
            "component_type": "agent",
            "created_at": 1234567890,
            "deleted_at": None,
        }

        response = client.post("/components/agent-1/restore")

        assert response.status_code == 409
        assert response.json()["detail"] == "Component is not archived"


class TestArchivedComponentDiscovery:
    """Archived components must be reachable through the read routes.

    Nothing else hands a client an archived component_id - POST /components
    answers identically for a live and an archived id - so without
    include_deleted the restore route can only be called for an id the caller
    happened to remember."""

    @pytest.fixture
    def arch_db(self, tmp_path):
        from agno.db.sqlite import SqliteDb

        db = SqliteDb(id="archived-db", db_file=str(tmp_path / "archived.db"))
        for component_id in ("live-1", "archived-1"):
            db.create_component_with_config(
                component_id=component_id,
                component_type=ComponentType.AGENT,
                name=component_id,
                config={"name": component_id},
                stage="published",
                user_id="user-A",
            )
        assert db.delete_component("archived-1", user_id="user-A") is True
        return db

    @pytest.fixture
    def arch_client(self, arch_db, settings):
        app = FastAPI()
        app.include_router(get_components_router(os_db=arch_db, settings=settings))
        return TestClient(app)

    def _scoped_client(self, db, settings, user_id):
        """A client scoped to a regular (non-admin) user with isolation on."""
        app = FastAPI()

        @app.middleware("http")
        async def add_jwt_user(request, call_next):
            request.state.user_isolation_enabled = True
            request.state.user_id = user_id
            request.state.scopes = []
            return await call_next(request)

        app.include_router(get_components_router(os_db=db, settings=settings))
        return TestClient(app)

    def test_list_omits_archived_by_default(self, arch_client):
        response = arch_client.get("/components")
        assert response.status_code == 200
        data = response.json()
        assert [c["component_id"] for c in data["data"]] == ["live-1"]
        assert data["meta"]["total_count"] == 1

    def test_list_with_include_deleted_returns_archived(self, arch_client):
        response = arch_client.get("/components?include_deleted=true")
        assert response.status_code == 200
        data = response.json()
        assert {c["component_id"] for c in data["data"]} == {"live-1", "archived-1"}
        assert data["meta"]["total_count"] == 2

    def test_list_labels_archived_rows_with_deleted_at(self, arch_client):
        response = arch_client.get("/components?include_deleted=true")
        rows = {c["component_id"]: c for c in response.json()["data"]}
        assert isinstance(rows["archived-1"]["deleted_at"], int)
        # Omitted for live rows: every component route excludes None fields.
        assert "deleted_at" not in rows["live-1"]

    def test_get_one_404s_for_archived_by_default(self, arch_client):
        assert arch_client.get("/components/archived-1").status_code == 404

    def test_get_one_with_include_deleted_returns_archived(self, arch_client):
        response = arch_client.get("/components/archived-1?include_deleted=true")
        assert response.status_code == 200
        body = response.json()
        assert body["component_id"] == "archived-1"
        assert isinstance(body["deleted_at"], int)

    def test_get_one_live_component_carries_no_deleted_at(self, arch_client):
        response = arch_client.get("/components/live-1?include_deleted=true")
        assert response.status_code == 200
        assert "deleted_at" not in response.json()

    def test_owner_sees_own_archived_component(self, arch_db, settings):
        """Positive control for the isolation test below."""
        owner_client = self._scoped_client(arch_db, settings, "user-A")
        listed = owner_client.get("/components?include_deleted=true")
        assert "archived-1" in {c["component_id"] for c in listed.json()["data"]}
        assert owner_client.get("/components/archived-1?include_deleted=true").status_code == 200

    def test_include_deleted_does_not_widen_visibility_across_owners(self, arch_db, settings):
        """include_deleted relaxes the tombstone filter, never the owner filter.

        Both halves belong in one test: the non-owner half alone also holds
        when include_deleted is ignored altogether and the archived row reaches
        nobody, so it is paired with the owner who must receive that same row
        from the same flag."""
        owner_client = self._scoped_client(arch_db, settings, "user-A")
        other_client = self._scoped_client(arch_db, settings, "user-B")

        owner_listed = owner_client.get("/components?include_deleted=true")
        assert owner_listed.status_code == 200
        assert {c["component_id"] for c in owner_listed.json()["data"]} == {"live-1", "archived-1"}
        assert owner_listed.json()["meta"]["total_count"] == 2
        assert owner_client.get("/components/archived-1?include_deleted=true").status_code == 200

        # include_deleted relaxes the tombstone filter for the OWNER's history.
        # For everyone else archiving is the off-switch: user-B keeps the
        # published live row and loses the archived one, flag or no flag.
        listed = other_client.get("/components?include_deleted=true")
        assert listed.status_code == 200
        assert {c["component_id"] for c in listed.json()["data"]} == {"live-1"}
        assert listed.json()["meta"]["total_count"] == 1

        assert other_client.get("/components/archived-1?include_deleted=true").status_code == 404
        assert other_client.get("/components/live-1?include_deleted=true").status_code == 200

    def test_include_deleted_keeps_unowned_archived_components_shared(self, arch_db, settings):
        """An unowned row is shared, and archiving it does not make it private.

        The tombstone filter and the owner filter are independent, so a scoped
        caller reads a shared archived row under include_deleted the same way it
        already reads a shared live row without the flag."""
        for component_id in ("shared-live", "shared-archived"):
            arch_db.create_component_with_config(
                component_id=component_id,
                component_type=ComponentType.AGENT,
                name=component_id,
                config={"name": component_id},
                stage="published",
            )
        assert arch_db.delete_component("shared-archived") is True

        other_client = self._scoped_client(arch_db, settings, "user-B")

        # The live precedent this pins against: an unowned row lists for a
        # non-owner. user-A's published live-1 lists too -- publishing puts it on
        # the platform -- while her archived-1 stays withdrawn.
        default_listed = other_client.get("/components")
        assert default_listed.status_code == 200
        assert {c["component_id"] for c in default_listed.json()["data"]} == {"shared-live", "live-1"}
        assert default_listed.json()["meta"]["total_count"] == 2
        assert other_client.get("/components/shared-archived").status_code == 404

        listed = other_client.get("/components?include_deleted=true")
        assert listed.status_code == 200
        assert {c["component_id"] for c in listed.json()["data"]} == {"shared-live", "shared-archived", "live-1"}
        assert listed.json()["meta"]["total_count"] == 3
        # Another owner's archived row is withdrawn from her even under the flag.
        assert other_client.get("/components/archived-1?include_deleted=true").status_code == 404

        fetched = other_client.get("/components/shared-archived?include_deleted=true")
        assert fetched.status_code == 200
        assert isinstance(fetched.json()["deleted_at"], int)

    def test_discover_then_restore_round_trip(self, arch_client, arch_db):
        """The full flow a frontend performs: find the archived id, restore it,
        and read it back as a live component."""
        listed = arch_client.get("/components?include_deleted=true")
        archived_ids = [c["component_id"] for c in listed.json()["data"] if c.get("deleted_at") is not None]
        assert archived_ids == ["archived-1"]

        restored = arch_client.post(f"/components/{archived_ids[0]}/restore")
        assert restored.status_code == 200
        assert "deleted_at" not in restored.json()

        assert arch_client.get("/components/archived-1").status_code == 200
        assert arch_db.get_component("archived-1") is not None
        relisted = arch_client.get("/components")
        assert {c["component_id"] for c in relisted.json()["data"]} == {"live-1", "archived-1"}

    def test_clickhouse_get_component_stub_accepts_include_deleted(self):
        """The restore route calls get_component(..., include_deleted=True), so
        every BaseDb implementation must accept it or restore raises TypeError
        and answers 500. clickhouse-connect is an optional dependency, so the
        stub's signature is read from source rather than imported."""
        import ast
        from pathlib import Path

        import agno.db

        source = (Path(agno.db.__file__).parent / "clickhouse" / "clickhouse.py").read_text()
        stub = next(
            node
            for cls in ast.parse(source).body
            if isinstance(cls, ast.ClassDef) and cls.name == "ClickhouseDb"
            for node in cls.body
            if isinstance(node, ast.FunctionDef) and node.name == "get_component"
        )
        assert "include_deleted" in {arg.arg for arg in stub.args.args}


# =============================================================================
# _resolve_db_in_config Tests
# =============================================================================
#
# These cover the components-router-specific merge behavior when a payload
# references a db by id: only whitelisted table-name fields are accepted from
# the caller; connection-defining fields (type / db_url / db_file / db_schema /
# id) always come from the resolved db so a caller cannot redirect a
# referenced db to a different backend through this path.


class TestResolveDbInConfig:
    """Tests for the _resolve_db_in_config helper in the components router."""

    def _make_os_db(self, tmp_path):
        from agno.db.sqlite.sqlite import SqliteDb

        return SqliteDb(db_file=str(tmp_path / "os.db"))

    def test_no_db_in_config_is_noop(self, tmp_path):
        from agno.os.routers.components.components import _resolve_db_in_config

        os_db = self._make_os_db(tmp_path)
        config = {"name": "agent"}

        out = _resolve_db_in_config(dict(config), os_db, None)

        assert out == config

    def test_db_none_is_removed(self, tmp_path):
        from agno.os.routers.components.components import _resolve_db_in_config

        os_db = self._make_os_db(tmp_path)

        out = _resolve_db_in_config({"name": "agent", "db": None}, os_db, None)

        assert "db" not in out

    def test_db_without_id_is_passed_through(self, tmp_path):
        from agno.os.routers.components.components import _resolve_db_in_config

        os_db = self._make_os_db(tmp_path)
        payload = {"db": {"type": "sqlite", "session_table": "custom"}}

        out = _resolve_db_in_config(dict(payload), os_db, None)

        assert out["db"] == payload["db"]

    def test_matching_id_merges_table_overrides_onto_resolved_db(self, tmp_path):
        """The reported bug: table-name overrides in the payload were being
        replaced with the resolved db's defaults."""
        from agno.os.routers.components.components import _resolve_db_in_config

        os_db = self._make_os_db(tmp_path)
        payload = {
            "db": {
                "id": os_db.id,
                "session_table": "custom_sessions",
                "memory_table": "custom_memories",
            },
        }

        out = _resolve_db_in_config(dict(payload), os_db, None)

        assert out["db"]["session_table"] == "custom_sessions"
        assert out["db"]["memory_table"] == "custom_memories"
        # Connection metadata is filled in from the resolved db.
        assert out["db"]["type"] == "sqlite"
        assert out["db"]["db_file"] == os_db.db_file
        # Fields the caller didn't override inherit os_db's values.
        assert out["db"]["knowledge_table"] == os_db.knowledge_table_name

    def test_matching_id_rejects_caller_override_of_connection_fields(self, tmp_path):
        """Whitelist: a caller cannot redirect a referenced db by
        supplying type / db_url / db_file / db_schema."""
        from agno.os.routers.components.components import _resolve_db_in_config

        os_db = self._make_os_db(tmp_path)
        payload = {
            "db": {
                "id": os_db.id,
                "type": "postgres",
                "db_url": "postgresql://attacker/evil",
                "db_file": "/evil.db",
                "db_schema": "public",
                "session_table": "custom_sessions",
            },
        }

        out = _resolve_db_in_config(dict(payload), os_db, None)

        resolved_db_dict = out["db"]
        # Connection fields MUST come from os_db, never from the caller.
        assert resolved_db_dict["type"] == "sqlite"
        assert resolved_db_dict["db_file"] == os_db.db_file
        assert resolved_db_dict.get("db_url") == os_db.db_url
        assert resolved_db_dict["id"] == os_db.id
        # The only caller-provided field that is allowed through is the
        # whitelisted table-name override.
        assert resolved_db_dict["session_table"] == "custom_sessions"

    def test_matching_id_ignores_non_whitelisted_keys(self, tmp_path):
        """Unknown keys in the payload must not leak into the stored config."""
        from agno.os.routers.components.components import _resolve_db_in_config

        os_db = self._make_os_db(tmp_path)
        payload = {
            "db": {
                "id": os_db.id,
                "session_table": "custom_sessions",
                "arbitrary_extension": "something",
            },
        }

        out = _resolve_db_in_config(dict(payload), os_db, None)

        assert "arbitrary_extension" not in out["db"]
        assert out["db"]["session_table"] == "custom_sessions"


class TestGuardHalfRejection:
    """A guard half a route cannot honour is rejected, never silently ignored:
    a caller who sent it believes it protected the write."""

    @pytest.fixture
    def guard_db(self, tmp_path):
        from agno.db.sqlite import SqliteDb

        db = SqliteDb(id="guard-half-db", db_file=str(tmp_path / "guard-half.db"))
        db.create_component_with_config(
            component_id="guarded",
            component_type=ComponentType.AGENT,
            name="guarded",
            config={"name": "guarded"},
            stage="published",
        )
        return db

    @pytest.fixture
    def guard_client(self, guard_db, settings):
        app = FastAPI()
        app.include_router(get_components_router(os_db=guard_db, settings=settings))
        return TestClient(app)

    def test_config_append_rejects_current_version_guard(self, guard_client):
        response = guard_client.post(
            "/components/guarded/configs",
            json={"config": {"name": "guarded"}, "guard": {"current_version": 1}},
        )
        assert response.status_code == 400
        assert "guard.latest_version" in response.json()["detail"]

    def test_set_current_rejects_latest_version_guard(self, guard_client):
        response = guard_client.post(
            "/components/guarded/configs/1/set-current",
            json={"guard": {"latest_version": 1}},
        )
        assert response.status_code == 400
        assert "guard.current_version" in response.json()["detail"]


class TestGuardHalfRejectionAllRoutes:
    """The guard-half rejection must fire at all four guard-bearing routes,
    not just the two previously covered."""

    @pytest.fixture
    def gr_db(self, tmp_path):
        from agno.db.sqlite import SqliteDb

        db = SqliteDb(id="ghr-all", db_file=str(tmp_path / "ghr.db"))
        db.create_component_with_config(
            component_id="c1",
            component_type=ComponentType.AGENT,
            name="c1",
            config={"name": "c1"},
            stage="published",
        )
        return db

    @pytest.fixture
    def gr_client(self, gr_db, settings):
        app = FastAPI()
        app.include_router(get_components_router(os_db=gr_db, settings=settings))
        return TestClient(app)

    def test_patch_component_rejects_latest_version_guard(self, gr_client):
        r = gr_client.patch("/components/c1", json={"description": "x", "guard": {"latest_version": 1}})
        assert r.status_code == 400
        assert "guard.current_version" in r.json()["detail"]

    def test_patch_config_rejects_current_version_guard(self, gr_client):
        r = gr_client.patch(
            "/components/c1/configs/1", json={"config": {"name": "c1"}, "guard": {"current_version": 1}}
        )
        assert r.status_code == 400
        assert "guard.latest_version" in r.json()["detail"]


class TestScopedWriteThreading:
    """The write routes must hand the caller's scope to the DB writers.

    The route guard alone cannot give the in-transaction guarantee: the writer
    parameter defaults to None, so dropping the kwarg at one call site would be
    a silent, test-green regression of the atomic refusal. These pin the
    binding for every write call site, with the caller as the row's owner so
    the route guard passes and the call goes through.
    """

    _row = {
        "component_id": "agent-1",
        "name": "Agent 1",
        "component_type": "agent",
        "current_version": 1,
        "user_id": "user-x",
        "created_at": 1234567890,
    }
    _config = {
        "component_id": "agent-1",
        "version": 1,
        "config": {"name": "Agent 1"},
        "stage": "draft",
        "created_at": 1234567890,
    }

    def _client(self, mock_db, settings):
        app = FastAPI()

        @app.middleware("http")
        async def add_jwt_user(request, call_next):
            request.state.user_isolation_enabled = True
            request.state.user_id = "user-x"
            request.state.scopes = []
            return await call_next(request)

        app.include_router(get_components_router(os_db=mock_db, settings=settings))
        return TestClient(app)

    def test_create_config_threads_scope(self, mock_db, settings):
        mock_db.get_component.return_value = dict(self._row)
        mock_db.upsert_config.return_value = dict(self._config)
        client = self._client(mock_db, settings)

        assert client.post("/components/agent-1/configs", json={"config": {"name": "x"}}).status_code == 201
        assert mock_db.upsert_config.call_args.kwargs["user_id"] == "user-x"

    def test_update_config_threads_scope(self, mock_db, settings):
        mock_db.get_component.return_value = dict(self._row)
        mock_db.upsert_config.return_value = dict(self._config)
        client = self._client(mock_db, settings)

        assert client.patch("/components/agent-1/configs/1", json={"config": {"name": "x"}}).status_code == 200
        assert mock_db.upsert_config.call_args.kwargs["user_id"] == "user-x"

    def test_delete_config_threads_scope(self, mock_db, settings):
        mock_db.get_component.return_value = dict(self._row)
        mock_db.delete_config.return_value = True
        client = self._client(mock_db, settings)

        assert client.delete("/components/agent-1/configs/2").status_code == 204
        assert mock_db.delete_config.call_args.kwargs["user_id"] == "user-x"

    def test_set_current_threads_scope(self, mock_db, settings):
        mock_db.get_component.return_value = dict(self._row)
        mock_db.set_current_version.return_value = True
        client = self._client(mock_db, settings)

        assert client.post("/components/agent-1/configs/1/set-current").status_code == 200
        assert mock_db.set_current_version.call_args.kwargs["user_id"] == "user-x"

    def test_patch_pointer_move_threads_scope(self, mock_db, settings):
        mock_db.get_component.return_value = dict(self._row)
        mock_db.get_config.return_value = dict(self._config)
        mock_db.set_current_version.return_value = True
        mock_db.upsert_component.return_value = dict(self._row)
        client = self._client(mock_db, settings)

        assert client.patch("/components/agent-1", json={"current_version": 1}).status_code == 200
        assert mock_db.set_current_version.call_args.kwargs["user_id"] == "user-x"
        assert mock_db.upsert_component.call_args.kwargs["user_id"] == "user-x"
