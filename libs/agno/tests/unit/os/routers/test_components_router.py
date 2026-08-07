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

from agno.agent import Agent
from agno.db.base import (
    BaseDb,
    ComponentDependencyError,
    ComponentDraftRequiredError,
    ComponentLastConfigError,
    ComponentType,
    ComponentVersionConflictError,
    ComponentVersionGuard,
)
from agno.db.in_memory import InMemoryDb
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.routers.components import get_components_router
from agno.os.settings import AgnoAPISettings
from agno.registry import Registry
from agno.run import RunContext
from agno.tools.studio import StudioTools
from agno.tools.studio_schema import AgentCreate, ModelRef

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
    db.supports_component_persistence = True
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
    db.get_links = MagicMock(return_value=[])
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


@pytest.fixture
def sqlite_client(tmp_path, settings):
    """Create a components router backed by the real SQLite persistence layer."""
    db = SqliteDb(db_file=str(tmp_path / "components-router.db"))
    app = FastAPI()
    app.include_router(get_components_router(os_db=db, settings=settings))
    return TestClient(app), db


@pytest.fixture
def studio_sqlite_client(tmp_path, settings):
    """Real typed Studio control plane and generic router over one catalog."""
    db = SqliteDb(id="studio-boundary-db", db_file=str(tmp_path / "studio-boundary.db"))
    model = OpenAIResponses(id="gpt-5.4")
    registry = Registry(name="Studio boundary registry", models=[model], dbs=[db])
    studio = StudioTools(
        registry=registry,
        db=db,
        authorize=lambda _context, _access, _action: True,
        default_model=ModelRef(id="gpt-5.4", provider="OpenAI", name="OpenAIResponses"),
    )
    run_context = RunContext(run_id="studio-run", session_id="studio-session", user_id="studio-admin")
    app = FastAPI()
    app.include_router(get_components_router(os_db=db, settings=settings, registry=registry))
    return TestClient(app), db, studio, run_context


def _guard(latest_version=1, current_version=1):
    return {"guard": {"latest_version": latest_version, "current_version": current_version}}


# =============================================================================
# Router Capability Tests
# =============================================================================


class TestComponentPersistenceCapability:
    def test_router_rejects_unsupported_sync_db(self, settings):
        unsupported_db = _create_mock_db_class()()

        with pytest.raises(ValueError, match="component persistence support"):
            get_components_router(os_db=unsupported_db, settings=settings)

    def test_agentos_mounts_disabled_router_for_unsupported_sync_db(self):
        agent_os = AgentOS(db=InMemoryDb(), telemetry=False)

        response = TestClient(agent_os.get_app()).get("/components")

        assert response.status_code == 503
        assert "component persistence support" in response.json()["detail"]

    def test_agentos_reprovision_keeps_unsupported_sync_db_disabled(self):
        agent_os = AgentOS(db=InMemoryDb(), telemetry=False)
        app = agent_os.get_app()

        agent_os._reprovision_routers(app)
        response = TestClient(app).get("/components")

        assert response.status_code == 503
        assert "component persistence support" in response.json()["detail"]


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

    def test_create_component_rejects_removed_set_current_field(self, client, mock_db):
        response = client.post(
            "/components",
            json={"name": "Test", "component_type": "agent", "set_current": False},
        )

        assert response.status_code == 422
        mock_db.create_component_with_config.assert_not_called()

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
        """Draft teams may use a code-defined registry member without a durable link."""
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

    def test_create_published_team_rejects_code_defined_member_without_durable_pin(self, mock_db, settings):
        """A live registry object is not an exact version pin for publication."""
        from agno.agent.agent import Agent
        from agno.registry import Registry

        mock_db.get_component.return_value = None
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
                "stage": "published",
                "config": {"id": "my-team", "members": [{"type": "agent", "agent_id": "member-agent"}]},
            },
        )

        assert response.status_code == 400
        assert "durable published versions" in response.json()["detail"]
        assert "member-agent" in response.json()["detail"]
        mock_db.create_component_with_config.assert_not_called()

    def test_create_published_team_rejects_draft_only_db_member(self, client, mock_db):
        """A DB component without a current published version cannot be pinned."""
        mock_db.get_component.return_value = {"component_id": "member-agent", "current_version": None}

        response = client.post(
            "/components",
            json={
                "name": "My Team",
                "component_type": "team",
                "component_id": "my-team",
                "stage": "published",
                "config": {"id": "my-team", "members": [{"type": "agent", "agent_id": "member-agent"}]},
            },
        )

        assert response.status_code == 400
        assert "durable published versions" in response.json()["detail"]
        assert "member-agent" in response.json()["detail"]
        mock_db.create_component_with_config.assert_not_called()

    def test_create_draft_team_allows_draft_only_db_member_without_link(self, client, mock_db):
        """Draft composition remains flexible until every child can be pinned."""
        mock_db.get_component.return_value = {"component_id": "member-agent", "current_version": None}
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
                "stage": "draft",
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
        """A metadata edit appends a guarded draft and leaves the projection alone."""
        mock_db.get_component.return_value = {
            "component_id": "agent-1",
            "name": "Old Name",
            "component_type": "agent",
            "current_version": 1,
            "created_at": 1234567890,
        }
        mock_db.get_config.return_value = {
            "component_id": "agent-1",
            "version": 1,
            "stage": "published",
            "config": {"id": "agent-1", "name": "Old Name", "instructions": "Help"},
            "created_at": 1234567890,
        }
        mock_db.upsert_config.return_value = {
            "component_id": "agent-1",
            "version": 2,
            "stage": "draft",
            "config": {"id": "agent-1", "name": "New Name", "instructions": "Help"},
            "created_at": 1234567891,
        }

        response = client.patch("/components/agent-1", json={"name": "New Name", **_guard(1, 1)})

        assert response.status_code == 200
        data = response.json()
        assert data["version"] == 2
        assert data["stage"] == "draft"
        assert data["config"]["name"] == "New Name"
        mock_db.upsert_component.assert_not_called()
        mock_db.upsert_config.assert_called_once_with(
            component_id="agent-1",
            config={
                "id": "agent-1",
                "name": "New Name",
                "instructions": "Help",
                "description": None,
                "metadata": None,
            },
            stage="draft",
            links=[],
            guard=ComponentVersionGuard(latest_version=1, current_version=1),
            projection=None,
        )

    def test_update_component_not_found(self, client, mock_db):
        """Test update_component returns 404 when not found."""
        mock_db.get_component.return_value = None

        response = client.patch("/components/nonexistent", json={"name": "New Name", **_guard()})

        assert response.status_code == 404

    def test_update_component_rejects_direct_current_pointer_mutation(self, client, mock_db):
        """Current-version changes must use the guarded set-current endpoint."""
        response = client.patch("/components/agent-1", json={"current_version": 2, **_guard()})

        assert response.status_code == 422
        mock_db.upsert_component.assert_not_called()

    def test_update_component_requires_guard_and_nonempty_patch(self, client, mock_db):
        assert client.patch("/components/agent-1", json={"name": "New Name"}).status_code == 422
        mock_db.get_component.return_value = {
            "component_id": "agent-1",
            "component_type": "agent",
            "current_version": 1,
        }
        mock_db.get_config.return_value = {
            "component_id": "agent-1",
            "version": 1,
            "stage": "published",
            "config": {"id": "agent-1", "name": "Agent"},
        }
        assert client.patch("/components/agent-1", json=_guard()).status_code == 400
        mock_db.upsert_config.assert_not_called()

    def test_update_component_guard_rejects_null_latest_version(self, client, mock_db):
        response = client.patch(
            "/components/agent-1",
            json={"name": "New Name", "guard": {"latest_version": None, "current_version": None}},
        )

        assert response.status_code == 422
        mock_db.upsert_config.assert_not_called()


# =============================================================================
# Delete Component Tests
# =============================================================================


class TestDeleteComponent:
    """Tests for DELETE /components/{component_id} endpoint."""

    def test_delete_component_success(self, client, mock_db):
        """Archive is guarded and projects the current published config."""
        mock_db.get_component.return_value = {
            "component_id": "agent-1",
            "component_type": "agent",
            "current_version": 1,
        }
        mock_db.get_config.return_value = {
            "component_id": "agent-1",
            "version": 1,
            "stage": "published",
            "config": {"name": "Published", "description": "Current", "metadata": {"release": 1}},
        }
        mock_db.delete_component.return_value = True

        response = client.request("DELETE", "/components/agent-1", json=_guard(2, 1))

        assert response.status_code == 204
        mock_db.delete_component.assert_called_once_with(
            "agent-1",
            hard_delete=False,
            guard=ComponentVersionGuard(latest_version=2, current_version=1),
            projection={"name": "Published", "description": "Current", "metadata": {"release": 1}},
        )

    def test_delete_component_not_found(self, client, mock_db):
        """Test delete_component returns 404 when not found."""
        mock_db.get_component.return_value = None

        response = client.request("DELETE", "/components/nonexistent", json=_guard())

        assert response.status_code == 404

    def test_delete_component_dependency_conflict_is_stable(self, client, mock_db):
        """The dependency-safe default must not turn an expected conflict into 500."""
        mock_db.delete_component.side_effect = ComponentDependencyError(
            "agent-1",
            [
                {
                    "parent_component_id": "team-1",
                    "parent_version": 3,
                    "link_kind": "member",
                    "link_key": "member_0",
                }
            ],
        )
        mock_db.get_component.return_value = {
            "component_id": "agent-1",
            "component_type": "agent",
            "current_version": 1,
        }
        mock_db.get_config.return_value = {
            "component_id": "agent-1",
            "version": 1,
            "stage": "published",
            "config": {"name": "Agent"},
        }

        response = client.request("DELETE", "/components/agent-1", json=_guard())

        assert response.status_code == 409
        assert response.json()["detail"] == "Cannot delete agent-1: it is referenced by 1 component link(s)"

    def test_delete_component_requires_guard(self, client, mock_db):
        response = client.delete("/components/agent-1")

        assert response.status_code == 422
        mock_db.delete_component.assert_not_called()


class TestGuardedGenericLifecycle:
    """Real SQLite regressions for append-only edits, CAS, and soft archive."""

    @staticmethod
    def _agent_config(name: str, description: str | None, metadata: dict | None):
        return {
            "id": "guarded-agent",
            "name": name,
            "instructions": "Be useful",
            "description": description,
            "metadata": metadata,
        }

    def _create(self, client, *, stage: str, name: str = "Version one"):
        return client.post(
            "/components",
            json={
                "component_id": "guarded-agent",
                "component_type": "agent",
                "name": name,
                "description": "Original description",
                "metadata": {"revision": 1},
                "stage": stage,
                "config": self._agent_config(
                    name,
                    "Original description",
                    {"revision": 1},
                ),
            },
        )

    @staticmethod
    def _stored_config_versions(db, component_id: str):
        table = db._get_table(table_type="component_configs")
        assert table is not None
        with db.Session() as session:
            return [
                row.version
                for row in session.execute(
                    table.select().where(table.c.component_id == component_id).order_by(table.c.version)
                ).fetchall()
            ]

    def test_patch_appends_generic_draft_and_preserves_current_projection(self, sqlite_client):
        client, db = sqlite_client
        assert self._create(client, stage="published").status_code == 201

        response = client.patch(
            "/components/guarded-agent",
            json={
                "name": "Draft edit",
                "description": None,
                "metadata": {"revision": 2},
                **_guard(1, 1),
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["version"] == 2
        assert data["stage"] == "draft"
        assert data["config"]["name"] == "Draft edit"
        assert data["config"]["description"] is None
        assert data["config"]["metadata"] == {"revision": 2}

        component = db.get_component("guarded-agent")
        assert component is not None
        assert component["current_version"] == 1
        assert component["name"] == "Version one"
        assert component["description"] == "Original description"
        assert component["metadata"] == {"revision": 1}

        stale = client.patch(
            "/components/guarded-agent",
            json={"name": "Lost update", **_guard(1, 1)},
        )
        assert stale.status_code == 409
        assert [row["version"] for row in db.list_configs("guarded-agent")] == [2, 1]

    def test_archive_uses_current_projection_and_preserves_all_history(self, sqlite_client):
        client, db = sqlite_client
        assert self._create(client, stage="published").status_code == 201
        assert (
            client.patch(
                "/components/guarded-agent",
                json={"name": "Unpublished draft", "metadata": {"revision": 2}, **_guard(1, 1)},
            ).status_code
            == 200
        )

        response = client.request("DELETE", "/components/guarded-agent", json=_guard(2, 1))

        assert response.status_code == 204
        archived = db.get_component("guarded-agent", include_deleted=True)
        assert archived is not None
        assert archived["deleted_at"] is not None
        assert archived["current_version"] == 1
        assert archived["name"] == "Version one"
        assert archived["metadata"] == {"revision": 1}
        assert self._stored_config_versions(db, "guarded-agent") == [1, 2]

    def test_draft_only_patch_and_archive_project_latest_draft(self, sqlite_client):
        client, db = sqlite_client
        assert self._create(client, stage="draft").status_code == 201
        assert (
            client.patch(
                "/components/guarded-agent",
                json={"name": "Latest draft", "metadata": {"revision": 2}, **_guard(1, None)},
            ).status_code
            == 200
        )

        component = db.get_component("guarded-agent")
        assert component is not None
        assert component["current_version"] is None
        assert component["name"] == "Latest draft"
        assert component["metadata"] == {"revision": 2}

        assert (
            client.request(
                "DELETE",
                "/components/guarded-agent",
                json=_guard(2, None),
            ).status_code
            == 204
        )
        archived = db.get_component("guarded-agent", include_deleted=True)
        assert archived is not None
        assert archived["name"] == "Latest draft"
        assert archived["metadata"] == {"revision": 2}
        assert self._stored_config_versions(db, "guarded-agent") == [1, 2]

    def test_delete_latest_draft_requires_fresh_guard_and_restores_draft_projection(self, sqlite_client):
        client, db = sqlite_client
        assert self._create(client, stage="draft").status_code == 201
        assert (
            client.patch(
                "/components/guarded-agent",
                json={"name": "Version two", "metadata": {"revision": 2}, **_guard(1, None)},
            ).status_code
            == 200
        )

        stale = client.request(
            "DELETE",
            "/components/guarded-agent/configs/2",
            json=_guard(1, None),
        )
        assert stale.status_code == 409
        assert db.get_config("guarded-agent", version=2) is not None

        deleted = client.request(
            "DELETE",
            "/components/guarded-agent/configs/2",
            json=_guard(2, None),
        )
        assert deleted.status_code == 204
        assert db.get_config("guarded-agent", version=2) is None
        component = db.get_component("guarded-agent")
        assert component is not None
        assert component["name"] == "Version one"
        assert component["metadata"] == {"revision": 1}
        assert self._stored_config_versions(db, "guarded-agent") == [1, 2]

    def test_generic_creation_rejects_reserved_studio_manifest(self, sqlite_client):
        client, db = sqlite_client
        config = self._agent_config("Version one", "Original description", {"revision": 1})
        config["_agno_studio"] = {"schema_version": 999, "request": {}}
        response = client.post(
            "/components",
            json={
                "component_id": "guarded-agent",
                "component_type": "agent",
                "name": "Version one",
                "stage": "draft",
                "config": config,
            },
        )

        assert response.status_code == 400
        assert "reserved for StudioTools" in response.json()["detail"]
        assert db.get_component("guarded-agent") is None


class TestStudioWriteIsolation:
    """The generic Components API is read-only for Studio-owned records."""

    def test_generic_config_append_cannot_claim_studio_manifest_namespace(self, sqlite_client):
        client, db = sqlite_client
        assert (
            client.post(
                "/components",
                json={
                    "component_id": "generic-agent",
                    "component_type": "agent",
                    "name": "Generic agent",
                    "config": {"id": "generic-agent", "name": "Generic agent"},
                },
            ).status_code
            == 201
        )

        response = client.post(
            "/components/generic-agent/configs",
            json={
                "config": {
                    "id": "generic-agent",
                    "name": "Forged Studio version",
                    "_agno_studio": {"schema_version": 2, "request": {}},
                },
                **_guard(1, None),
            },
        )

        assert response.status_code == 400
        assert "reserved for StudioTools" in response.json()["detail"]
        assert [row["version"] for row in db.list_configs("generic-agent")] == [1]

    def test_all_generic_mutations_reject_studio_owned_component_without_corrupting_discovery(
        self, studio_sqlite_client
    ):
        client, db, studio, run_context = studio_sqlite_client
        created = studio.create_agent(
            AgentCreate(
                component_id="studio-agent",
                name="Studio agent",
                instructions="Keep the typed request intact.",
            ),
            _agno_run_context=run_context,
        )
        assert created.ok is True
        assert created.data is not None and created.data.version == 1

        responses = [
            client.patch(
                "/components/studio-agent",
                json={"name": "Generic rename", **_guard(1, None)},
            ),
            client.request(
                "DELETE",
                "/components/studio-agent",
                json=_guard(1, None),
            ),
            client.post(
                "/components/studio-agent/configs",
                json={
                    "config": {
                        "id": "studio-agent",
                        "name": "Raw overwrite",
                        "instructions": "Bypass the typed manifest.",
                    },
                    **_guard(1, None),
                },
            ),
            client.patch(
                "/components/studio-agent/configs/1",
                json={"stage": "published", **_guard(1, None)},
            ),
            client.request(
                "DELETE",
                "/components/studio-agent/configs/1",
                json=_guard(1, None),
            ),
            client.post(
                "/components/studio-agent/configs/1/set-current",
                json=_guard(1, None),
            ),
        ]

        for response in responses:
            assert response.status_code == 409
            assert response.json()["detail"] == "Studio-owned components must be mutated through StudioTools."

        configs = db.list_configs("studio-agent", include_config=True)
        assert [row["version"] for row in configs] == [1]
        assert "_agno_studio" in configs[0]["config"]
        component = db.get_component("studio-agent")
        assert component is not None and component["current_version"] is None

        listed = studio.list_agents(_agno_run_context=run_context)
        assert listed.ok is True
        assert listed.data is not None
        assert [(item.component_id, item.latest_version) for item in listed.data] == [("studio-agent", 1)]

        read_response = client.get("/components/studio-agent/configs/1")
        assert read_response.status_code == 200
        assert "_agno_studio" in read_response.json()["config"]


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
        """Config summaries remain valid when the payload is intentionally omitted."""
        mock_db.list_configs.return_value = [
            {
                "component_id": "agent-1",
                "version": 2,
                "stage": "published",
                "created_at": 1234567890,
            }
        ]

        response = client.get("/components/agent-1/configs?include_config=false")

        assert response.status_code == 200
        assert response.json() == [
            {
                "component_id": "agent-1",
                "version": 2,
                "stage": "published",
                "created_at": 1234567890,
            }
        ]
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
            json={"config": {"name": "Agent"}, "stage": "draft", **_guard()},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["version"] == 1
        mock_db.upsert_config.assert_called_once_with(
            component_id="agent-1",
            version=None,
            config={"name": "Agent", "description": None, "metadata": None},
            label=None,
            stage="draft",
            notes=None,
            links=None,
            guard=ComponentVersionGuard(latest_version=1, current_version=1),
            projection=None,
        )

    def test_create_config_stores_inherited_fields_and_explicit_nulls(self, client, mock_db):
        mock_db.get_component.return_value = {
            "component_id": "agent-1",
            "component_type": "agent",
            "name": "Current name",
            "description": "Current description",
            "metadata": {"release": 1},
            "current_version": 1,
        }
        mock_db.upsert_config.return_value = {
            "component_id": "agent-1",
            "version": 2,
            "config": {"instructions": "v2"},
            "stage": "draft",
            "created_at": 1234567890,
        }

        response = client.post(
            "/components/agent-1/configs",
            json={"config": {"instructions": "v2", "description": None}, "stage": "draft", **_guard()},
        )

        assert response.status_code == 201
        assert mock_db.upsert_config.call_args.kwargs["config"] == {
            "instructions": "v2",
            "name": "Current name",
            "description": None,
            "metadata": {"release": 1},
        }

    def test_create_config_requires_guard(self, client, mock_db):
        response = client.post("/components/agent-1/configs", json={"config": {"name": "Agent"}})

        assert response.status_code == 422
        mock_db.upsert_config.assert_not_called()

    def test_agent_config_rejects_caller_owned_component_links(self, client, mock_db):
        mock_db.get_component.return_value = {
            "component_id": "agent-1",
            "component_type": "agent",
            "current_version": 1,
        }

        response = client.post(
            "/components/agent-1/configs",
            json={
                "config": {"name": "Agent"},
                "links": [
                    {
                        "link_kind": "step_agent",
                        "link_key": "forged",
                        "child_component_id": "victim",
                        "child_version": 1,
                        "position": 0,
                    }
                ],
                **_guard(),
            },
        )

        assert response.status_code == 400
        assert "do not support component links" in response.json()["detail"]
        mock_db.upsert_config.assert_not_called()

    def test_create_published_config_projects_catalog_fields(self, client, mock_db):
        config = {
            "name": "Published Agent",
            "description": "Projected description",
            "metadata": {"release": 2},
            "instructions": "Be useful",
        }
        mock_db.upsert_config.return_value = {
            "component_id": "agent-1",
            "version": 2,
            "config": config,
            "stage": "published",
            "created_at": 1234567890,
        }

        response = client.post(
            "/components/agent-1/configs",
            json={"config": config, "stage": "published", **_guard(1, 1)},
        )

        assert response.status_code == 201
        assert mock_db.upsert_config.call_args.kwargs["projection"] == {
            "name": "Published Agent",
            "description": "Projected description",
            "metadata": {"release": 2},
        }

    def test_create_draft_config_projects_catalog_fields_before_first_publish(self, client, mock_db):
        config = {
            "name": "Second draft",
            "description": "Latest draft projection",
            "metadata": {"revision": 2},
        }
        mock_db.get_component.return_value = {
            "component_id": "agent-1",
            "component_type": "agent",
            "current_version": None,
        }
        mock_db.upsert_config.return_value = {
            "component_id": "agent-1",
            "version": 2,
            "config": config,
            "stage": "draft",
            "created_at": 1234567890,
        }

        response = client.post(
            "/components/agent-1/configs",
            json={"config": config, "stage": "draft", **_guard(1, None)},
        )

        assert response.status_code == 201
        assert mock_db.upsert_config.call_args.kwargs["projection"] == {
            "name": "Second draft",
            "description": "Latest draft projection",
            "metadata": {"revision": 2},
        }

    def test_create_config_maps_stale_guard_to_conflict(self, client, mock_db):
        mock_db.get_component.return_value = {
            "component_id": "agent-1",
            "component_type": "agent",
            "name": "Agent",
            "current_version": 1,
        }
        mock_db.upsert_config.side_effect = ComponentVersionConflictError(
            "agent-1",
            expected=ComponentVersionGuard(latest_version=1, current_version=1),
            actual=ComponentVersionGuard(latest_version=2, current_version=1),
        )

        response = client.post("/components/agent-1/configs", json={"config": {}, **_guard()})

        assert response.status_code == 409
        assert "version conflict" in response.json()["detail"]

    @pytest.mark.parametrize("removed_field", [{"version": 2}, {"set_current": False}])
    def test_create_config_rejects_removed_noop_fields(self, client, mock_db, removed_field):
        response = client.post("/components/agent-1/configs", json={"config": {}, **_guard(), **removed_field})

        assert response.status_code == 422
        mock_db.upsert_config.assert_not_called()

    def test_create_config_handles_value_error(self, client, mock_db):
        """Test create_config returns 400 on ValueError."""
        mock_db.upsert_config.side_effect = ValueError("Invalid config")

        response = client.post(
            "/components/agent-1/configs",
            json={"config": {}, **_guard()},
        )

        assert response.status_code == 400


class TestTeamLinkTrustBoundary:
    """Published Team configs must derive durable member pins server-side."""

    @staticmethod
    def _create_component(
        client,
        *,
        component_id: str,
        component_type: str,
        stage: str,
        config: dict,
    ):
        return client.post(
            "/components",
            json={
                "component_id": component_id,
                "name": config.get("name", component_id),
                "component_type": component_type,
                "stage": stage,
                "config": config,
            },
        )

    def test_draft_team_promotion_rejects_draft_only_member(self, sqlite_client):
        client, db = sqlite_client
        assert (
            self._create_component(
                client,
                component_id="draft-child",
                component_type="agent",
                stage="draft",
                config={"id": "draft-child", "name": "Draft child"},
            ).status_code
            == 201
        )
        assert (
            self._create_component(
                client,
                component_id="draft-team",
                component_type="team",
                stage="draft",
                config={
                    "id": "draft-team",
                    "name": "Draft team",
                    "members": [{"type": "agent", "agent_id": "draft-child"}],
                },
            ).status_code
            == 201
        )

        response = client.patch(
            "/components/draft-team/configs/1",
            json={"stage": "published", **_guard(1, None)},
        )

        assert response.status_code == 400
        assert "durable published versions" in response.json()["detail"]
        component = db.get_component("draft-team")
        draft = db.get_config("draft-team", version=1)
        assert component is not None and component["current_version"] is None
        assert draft is not None and draft["stage"] == "draft"
        assert db.get_links("draft-team", 1) == []

    def test_draft_team_promotion_derives_pin_after_member_is_published(self, sqlite_client):
        client, db = sqlite_client
        assert (
            self._create_component(
                client,
                component_id="child",
                component_type="agent",
                stage="draft",
                config={"id": "child", "name": "Child"},
            ).status_code
            == 201
        )
        assert (
            self._create_component(
                client,
                component_id="team",
                component_type="team",
                stage="draft",
                config={
                    "id": "team",
                    "name": "Team",
                    "members": [{"type": "agent", "agent_id": "child"}],
                },
            ).status_code
            == 201
        )
        assert db.get_links("team", 1) == []

        child_publish = client.patch(
            "/components/child/configs/1",
            json={"stage": "published", **_guard(1, None)},
        )
        assert child_publish.status_code == 200

        team_publish = client.patch(
            "/components/team/configs/1",
            json={"stage": "published", **_guard(1, None)},
        )

        assert team_publish.status_code == 200
        assert team_publish.json()["stage"] == "published"
        component = db.get_component("team")
        assert component is not None and component["current_version"] == 1
        links = db.get_links("team", 1)
        assert [(link["child_component_id"], link["child_version"]) for link in links] == [("child", 1)]

    def test_published_team_config_create_rejects_draft_only_member(self, sqlite_client):
        client, db = sqlite_client
        assert (
            self._create_component(
                client,
                component_id="draft-child",
                component_type="agent",
                stage="draft",
                config={"id": "draft-child", "name": "Draft child"},
            ).status_code
            == 201
        )
        assert (
            self._create_component(
                client,
                component_id="team",
                component_type="team",
                stage="draft",
                config={"id": "team", "name": "Team", "members": []},
            ).status_code
            == 201
        )

        response = client.post(
            "/components/team/configs",
            json={
                "stage": "published",
                "config": {
                    "id": "team",
                    "name": "Team",
                    "members": [{"type": "agent", "agent_id": "draft-child"}],
                },
                **_guard(1, None),
            },
        )

        assert response.status_code == 400
        assert "durable published versions" in response.json()["detail"]
        assert [row["version"] for row in db.list_configs("team")] == [1]

    def test_team_config_create_rejects_caller_supplied_mismatched_links(self, sqlite_client):
        client, db = sqlite_client
        for child_id in ("member-a", "member-b"):
            assert (
                self._create_component(
                    client,
                    component_id=child_id,
                    component_type="agent",
                    stage="published",
                    config={"id": child_id, "name": child_id},
                ).status_code
                == 201
            )
        assert (
            self._create_component(
                client,
                component_id="team",
                component_type="team",
                stage="draft",
                config={"id": "team", "name": "Team", "members": []},
            ).status_code
            == 201
        )

        response = client.post(
            "/components/team/configs",
            json={
                "stage": "draft",
                "config": {
                    "id": "team",
                    "name": "Team",
                    "members": [{"type": "agent", "agent_id": "member-a"}],
                },
                "links": [
                    {
                        "link_kind": "member",
                        "link_key": "member_0",
                        "child_component_id": "member-b",
                        "child_version": 1,
                        "position": 0,
                        "meta": {"type": "agent"},
                    }
                ],
                **_guard(1, None),
            },
        )

        assert response.status_code == 400
        assert "derived from config.members" in response.json()["detail"]
        assert [row["version"] for row in db.list_configs("team")] == [1]

    def test_draft_team_config_keeps_flexible_member_and_persists_resolvable_pin(self, sqlite_client):
        client, db = sqlite_client
        assert (
            self._create_component(
                client,
                component_id="draft-child",
                component_type="agent",
                stage="draft",
                config={"id": "draft-child", "name": "Draft child"},
            ).status_code
            == 201
        )
        assert (
            self._create_component(
                client,
                component_id="published-child",
                component_type="agent",
                stage="published",
                config={"id": "published-child", "name": "Published child"},
            ).status_code
            == 201
        )
        assert (
            self._create_component(
                client,
                component_id="team",
                component_type="team",
                stage="draft",
                config={"id": "team", "name": "Team", "members": []},
            ).status_code
            == 201
        )

        response = client.post(
            "/components/team/configs",
            json={
                "stage": "draft",
                "config": {
                    "id": "team",
                    "name": "Team",
                    "members": [
                        {"type": "agent", "agent_id": "draft-child"},
                        {"type": "agent", "agent_id": "published-child"},
                    ],
                },
                **_guard(1, None),
            },
        )

        assert response.status_code == 201
        assert response.json()["version"] == 2
        links = db.get_links("team", 2)
        assert [(link["link_key"], link["child_component_id"], link["child_version"]) for link in links] == [
            ("member_1", "published-child", 1)
        ]

    @pytest.mark.parametrize(
        "members,detail",
        [
            ({"type": "agent", "agent_id": "child"}, "must be a list"),
            ({}, "must be a list"),
            ("", "must be a list"),
            (0, "must be a list"),
            (False, "must be a list"),
            (None, "must be a list"),
            (["child"], "must be an object"),
            ([{"type": "unknown", "agent_id": "child"}], "must be 'agent' or 'team'"),
            ([{"type": "agent", "agent_id": ""}], "must be a non-empty string"),
            (
                [{"type": "agent", "agent_id": "child", "team_id": "other"}],
                "exactly one of agent_id or team_id",
            ),
        ],
    )
    def test_team_members_fail_closed_before_component_creation(self, sqlite_client, members, detail):
        client, db = sqlite_client

        response = self._create_component(
            client,
            component_id="malformed-team",
            component_type="team",
            stage="draft",
            config={"id": "malformed-team", "name": "Malformed team", "members": members},
        )

        assert response.status_code == 400
        assert detail in response.json()["detail"]
        assert db.get_component("malformed-team") is None

    def test_explicit_empty_team_members_list_is_allowed(self, sqlite_client):
        client, db = sqlite_client

        response = self._create_component(
            client,
            component_id="empty-team",
            component_type="team",
            stage="draft",
            config={"id": "empty-team", "name": "Empty team", "members": []},
        )

        assert response.status_code == 201
        assert db.get_component("empty-team") is not None
        assert db.get_links("empty-team", 1) == []


class TestWorkflowLinkTrustBoundary:
    """Workflow links are validated and derived from every nested Step."""

    @staticmethod
    def _create_component(
        client,
        *,
        component_id: str,
        component_type: str,
        stage: str,
        config: dict,
    ):
        return client.post(
            "/components",
            json={
                "component_id": component_id,
                "name": config.get("name", component_id),
                "component_type": component_type,
                "stage": stage,
                "config": config,
            },
        )

    def test_published_workflow_rejects_draft_only_step_component_atomically(self, sqlite_client):
        client, db = sqlite_client
        assert (
            self._create_component(
                client,
                component_id="draft-agent",
                component_type="agent",
                stage="draft",
                config={"id": "draft-agent", "name": "Draft agent"},
            ).status_code
            == 201
        )

        response = self._create_component(
            client,
            component_id="published-workflow",
            component_type="workflow",
            stage="published",
            config={
                "id": "published-workflow",
                "name": "Published workflow",
                "steps": [{"type": "Step", "step_id": "draft-step", "name": "Draft step", "agent_id": "draft-agent"}],
            },
        )

        assert response.status_code == 400
        assert "durable published versions" in response.json()["detail"]
        assert db.get_component("published-workflow") is None

    def test_published_workflow_derives_exact_links_through_nested_branches(self, sqlite_client):
        client, db = sqlite_client
        assert (
            self._create_component(
                client,
                component_id="agent-child",
                component_type="agent",
                stage="published",
                config={"id": "agent-child", "name": "Agent child"},
            ).status_code
            == 201
        )
        assert (
            self._create_component(
                client,
                component_id="team-child",
                component_type="team",
                stage="published",
                config={"id": "team-child", "name": "Team child", "members": []},
            ).status_code
            == 201
        )
        assert (
            self._create_component(
                client,
                component_id="workflow-child",
                component_type="workflow",
                stage="published",
                config={"id": "workflow-child", "name": "Workflow child", "steps": []},
            ).status_code
            == 201
        )

        response = self._create_component(
            client,
            component_id="workflow-parent",
            component_type="workflow",
            stage="published",
            config={
                "id": "workflow-parent",
                "name": "Workflow parent",
                "steps": [
                    {
                        "type": "Parallel",
                        "name": "parallel",
                        "steps": [
                            {
                                "type": "Step",
                                "step_id": "agent-step",
                                "name": "Agent step",
                                "agent_id": "agent-child",
                            },
                            {
                                "type": "Condition",
                                "name": "condition",
                                "steps": [
                                    {
                                        "type": "Step",
                                        "step_id": "team-step",
                                        "name": "Team step",
                                        "team_id": "team-child",
                                    }
                                ],
                                "else_steps": [
                                    {
                                        "type": "Router",
                                        "name": "router",
                                        "choices": [
                                            {
                                                "type": "Step",
                                                "step_id": "workflow-step",
                                                "name": "Workflow step",
                                                "workflow_id": "workflow-child",
                                            }
                                        ],
                                    }
                                ],
                            },
                        ],
                    }
                ],
            },
        )

        assert response.status_code == 201
        links = sorted(db.get_links("workflow-parent", 1), key=lambda link: link["position"])
        assert [
            (
                link["link_kind"],
                link["link_key"],
                link["child_component_id"],
                link["child_version"],
                link["position"],
            )
            for link in links
        ] == [
            ("step_agent", "agent-step", "agent-child", 1, 0),
            ("step_team", "team-step", "team-child", 1, 1),
            ("step_workflow", "workflow-step", "workflow-child", 1, 2),
        ]

    @pytest.mark.parametrize(
        "bad_step",
        [
            {"type": "Mystery", "steps": []},
            {
                "type": "Step",
                "step_id": "ambiguous",
                "agent_id": "agent-child",
                "team_id": "team-child",
            },
        ],
    )
    def test_malformed_workflow_reference_fails_closed_atomically(self, sqlite_client, bad_step):
        client, db = sqlite_client

        response = self._create_component(
            client,
            component_id="bad-workflow",
            component_type="workflow",
            stage="draft",
            config={"id": "bad-workflow", "name": "Bad workflow", "steps": [bad_step]},
        )

        assert response.status_code == 400
        assert db.get_component("bad-workflow") is None

    def test_unregistered_function_step_fails_closed_atomically(self, sqlite_client):
        client, db = sqlite_client

        response = self._create_component(
            client,
            component_id="missing-function-workflow",
            component_type="workflow",
            stage="draft",
            config={
                "id": "missing-function-workflow",
                "name": "Missing function workflow",
                "steps": [{"type": "Step", "step_id": "function-step", "executor_ref": "not_registered"}],
            },
        )

        assert response.status_code == 400
        assert "not_registered" in response.json()["detail"]
        assert db.get_component("missing-function-workflow") is None

    def test_ambiguous_registered_function_step_fails_closed(self, tmp_path, settings):
        def first_function():
            return None

        def second_function():
            return None

        first_function.__name__ = "duplicate_function"
        second_function.__name__ = "duplicate_function"
        db = SqliteDb(db_file=str(tmp_path / "ambiguous-workflow-function.db"))
        app = FastAPI()
        app.include_router(
            get_components_router(
                os_db=db,
                settings=settings,
                registry=Registry(functions=[first_function, second_function]),
            )
        )
        client = TestClient(app)

        response = self._create_component(
            client,
            component_id="ambiguous-function-workflow",
            component_type="workflow",
            stage="draft",
            config={
                "id": "ambiguous-function-workflow",
                "name": "Ambiguous function workflow",
                "steps": [{"type": "Step", "step_id": "function-step", "executor_ref": "duplicate_function"}],
            },
        )

        assert response.status_code == 400
        assert "ambiguous" in response.json()["detail"]
        assert db.get_component("ambiguous-function-workflow") is None

    def test_draft_workflow_keeps_draft_reference_flexible_and_pins_published_child(self, sqlite_client):
        client, db = sqlite_client
        assert (
            self._create_component(
                client,
                component_id="draft-child",
                component_type="agent",
                stage="draft",
                config={"id": "draft-child", "name": "Draft child"},
            ).status_code
            == 201
        )
        assert (
            self._create_component(
                client,
                component_id="published-child",
                component_type="agent",
                stage="published",
                config={"id": "published-child", "name": "Published child"},
            ).status_code
            == 201
        )

        response = self._create_component(
            client,
            component_id="draft-workflow",
            component_type="workflow",
            stage="draft",
            config={
                "id": "draft-workflow",
                "name": "Draft workflow",
                "steps": [
                    {"type": "Step", "step_id": "draft-step", "agent_id": "draft-child"},
                    {"type": "Step", "step_id": "published-step", "agent_id": "published-child"},
                ],
            },
        )

        assert response.status_code == 201
        links = db.get_links("draft-workflow", 1)
        assert [(link["link_key"], link["child_component_id"], link["child_version"]) for link in links] == [
            ("published-step", "published-child", 1)
        ]

    def test_workflow_config_create_rejects_caller_supplied_links(self, sqlite_client):
        client, db = sqlite_client
        assert (
            self._create_component(
                client,
                component_id="workflow",
                component_type="workflow",
                stage="draft",
                config={"id": "workflow", "name": "Workflow", "steps": []},
            ).status_code
            == 201
        )

        response = client.post(
            "/components/workflow/configs",
            json={
                "config": {"id": "workflow", "name": "Workflow", "steps": []},
                "links": [
                    {
                        "link_kind": "step_agent",
                        "link_key": "forged",
                        "child_component_id": "other",
                        "child_version": 1,
                        "position": 0,
                    }
                ],
                **_guard(1, None),
            },
        )

        assert response.status_code == 400
        assert "derived from config.steps" in response.json()["detail"]
        assert [row["version"] for row in db.list_configs("workflow")] == [1]

    def test_workflow_promotion_derives_pin_after_child_is_published(self, sqlite_client):
        client, db = sqlite_client
        assert (
            self._create_component(
                client,
                component_id="child",
                component_type="agent",
                stage="draft",
                config={"id": "child", "name": "Child"},
            ).status_code
            == 201
        )
        assert (
            self._create_component(
                client,
                component_id="workflow",
                component_type="workflow",
                stage="draft",
                config={
                    "id": "workflow",
                    "name": "Workflow",
                    "steps": [{"type": "Step", "step_id": "child-step", "agent_id": "child"}],
                },
            ).status_code
            == 201
        )
        assert db.get_links("workflow", 1) == []

        rejected = client.patch(
            "/components/workflow/configs/1",
            json={"stage": "published", **_guard(1, None)},
        )
        assert rejected.status_code == 400
        assert db.get_links("workflow", 1) == []

        assert (
            client.patch(
                "/components/child/configs/1",
                json={"stage": "published", **_guard(1, None)},
            ).status_code
            == 200
        )
        published = client.patch(
            "/components/workflow/configs/1",
            json={"stage": "published", **_guard(1, None)},
        )

        assert published.status_code == 200
        links = db.get_links("workflow", 1)
        assert [(link["link_key"], link["child_component_id"], link["child_version"]) for link in links] == [
            ("child-step", "child", 1)
        ]

    def test_metadata_patch_copies_guarded_workflow_pins_without_retargeting(self, sqlite_client):
        client, db = sqlite_client
        assert (
            self._create_component(
                client,
                component_id="child",
                component_type="agent",
                stage="published",
                config={"id": "child", "name": "Child v1"},
            ).status_code
            == 201
        )
        assert (
            self._create_component(
                client,
                component_id="workflow",
                component_type="workflow",
                stage="draft",
                config={
                    "id": "workflow",
                    "name": "Workflow",
                    "steps": [{"type": "Step", "step_id": "child-step", "agent_id": "child"}],
                },
            ).status_code
            == 201
        )
        assert db.get_links("workflow", 1)[0]["child_version"] == 1

        assert (
            client.post(
                "/components/child/configs",
                json={
                    "stage": "published",
                    "config": {"id": "child", "name": "Child v2"},
                    **_guard(1, 1),
                },
            ).status_code
            == 201
        )
        assert db.get_component("child")["current_version"] == 2  # type: ignore[index]

        patched = client.patch(
            "/components/workflow",
            json={"description": "Metadata-only edit", **_guard(1, None)},
        )

        assert patched.status_code == 200
        assert patched.json()["version"] == 2
        links = db.get_links("workflow", 2)
        assert [(link["link_key"], link["child_component_id"], link["child_version"]) for link in links] == [
            ("child-step", "child", 1)
        ]


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
        """Test update_config publishes the latest draft with its projection."""
        mock_db.get_config.return_value = {
            "component_id": "agent-1",
            "version": 2,
            "config": {
                "name": "Updated Agent",
                "description": "Version two",
                "metadata": {"release": 2},
            },
            "stage": "draft",
            "created_at": 1234567890,
        }
        mock_db.upsert_config.return_value = {
            "component_id": "agent-1",
            "version": 2,
            "config": {"name": "Updated Agent"},
            "stage": "published",
            "created_at": 1234567890,
        }

        response = client.patch(
            "/components/agent-1/configs/2",
            json={"stage": "published", **_guard(2, 1)},
        )

        assert response.status_code == 200
        assert response.json()["stage"] == "published"
        mock_db.upsert_config.assert_called_once_with(
            component_id="agent-1",
            version=2,
            stage="published",
            guard=ComponentVersionGuard(latest_version=2, current_version=1),
            projection={
                "name": "Updated Agent",
                "description": "Version two",
                "metadata": {"release": 2},
            },
        )

    def test_update_config_requires_guard(self, client, mock_db):
        response = client.patch("/components/agent-1/configs/2", json={"stage": "published"})

        assert response.status_code == 422
        mock_db.upsert_config.assert_not_called()

    def test_update_config_maps_stale_guard_to_conflict(self, client, mock_db):
        mock_db.get_config.return_value = {
            "component_id": "agent-1",
            "version": 2,
            "config": {"name": "Agent"},
            "stage": "draft",
            "created_at": 1234567890,
        }
        mock_db.upsert_config.side_effect = ComponentVersionConflictError(
            "agent-1",
            expected=ComponentVersionGuard(latest_version=2, current_version=1),
            actual=ComponentVersionGuard(latest_version=3, current_version=1),
        )

        response = client.patch("/components/agent-1/configs/2", json={"stage": "published", **_guard(2, 1)})

        assert response.status_code == 409

    def test_update_config_rejects_payload_mutation(self, client, mock_db):
        response = client.patch(
            "/components/agent-1/configs/2",
            json={"stage": "published", "config": {"name": "Changed"}, **_guard(2, 1)},
        )

        assert response.status_code == 422
        mock_db.upsert_config.assert_not_called()

    def test_update_config_handles_value_error(self, client, mock_db):
        """Test update_config returns 400 on ValueError."""
        mock_db.get_config.return_value = {
            "component_id": "agent-1",
            "version": 1,
            "config": {},
            "stage": "draft",
            "created_at": 1234567890,
        }
        mock_db.upsert_config.side_effect = ValueError("Cannot update published config")

        response = client.patch(
            "/components/agent-1/configs/1",
            json={"stage": "published", **_guard()},
        )

        assert response.status_code == 400


# =============================================================================
# Delete Config Tests
# =============================================================================


class TestDeleteConfig:
    """Tests for DELETE /components/{component_id}/configs/{version} endpoint."""

    @staticmethod
    def _published_component(mock_db):
        mock_db.get_component.return_value = {
            "component_id": "agent-1",
            "component_type": "agent",
            "current_version": 1,
        }
        mock_db.get_config.return_value = {
            "component_id": "agent-1",
            "version": 1,
            "stage": "published",
            "config": {"name": "Published", "description": "Current"},
        }

    def test_delete_config_success(self, client, mock_db):
        """Test delete_config deletes config version."""
        self._published_component(mock_db)
        mock_db.delete_config.return_value = True

        response = client.request("DELETE", "/components/agent-1/configs/2", json=_guard(2, 1))

        assert response.status_code == 204
        mock_db.delete_config.assert_called_once_with(
            "agent-1",
            version=2,
            guard=ComponentVersionGuard(latest_version=2, current_version=1),
            projection={"name": "Published", "description": "Current", "metadata": None},
        )

    def test_delete_config_not_found(self, client, mock_db):
        """Test delete_config returns 404 when not found."""
        self._published_component(mock_db)
        mock_db.delete_config.return_value = False

        response = client.request("DELETE", "/components/agent-1/configs/999", json=_guard())

        assert response.status_code == 404

    def test_delete_config_handles_value_error(self, client, mock_db):
        """Test delete_config returns 400 on ValueError."""
        self._published_component(mock_db)
        mock_db.delete_config.side_effect = ValueError("Cannot delete current config")

        response = client.request("DELETE", "/components/agent-1/configs/1", json=_guard())

        assert response.status_code == 400

    def test_delete_config_dependency_conflict_is_stable(self, client, mock_db):
        self._published_component(mock_db)
        mock_db.delete_config.side_effect = ComponentDependencyError(
            "agent-1",
            [{"parent_component_id": "team-1", "parent_version": 2}],
            version=1,
        )

        response = client.request("DELETE", "/components/agent-1/configs/1", json=_guard())

        assert response.status_code == 409
        assert "referenced by 1 component link" in response.json()["detail"]

    def test_delete_sole_last_config_conflict_is_stable(self, client, mock_db):
        self._published_component(mock_db)
        mock_db.delete_config.side_effect = ComponentLastConfigError("agent-1", 1)

        response = client.request("DELETE", "/components/agent-1/configs/1", json=_guard())

        assert response.status_code == 409
        assert "last config" in response.json()["detail"]

    def test_delete_published_config_conflict_is_stable(self, client, mock_db):
        self._published_component(mock_db)
        mock_db.delete_config.side_effect = ComponentDraftRequiredError("agent-1", 1)

        response = client.request("DELETE", "/components/agent-1/configs/1", json=_guard())

        assert response.status_code == 409
        assert response.json()["detail"] == (
            "Cannot delete published config agent-1 v1; only draft configs can be deleted"
        )

    def test_delete_config_requires_guard(self, client, mock_db):
        response = client.delete("/components/agent-1/configs/2")

        assert response.status_code == 422
        mock_db.delete_config.assert_not_called()


# =============================================================================
# Set Current Config Tests
# =============================================================================


class TestSetCurrentConfig:
    """Tests for POST /components/{component_id}/configs/{version}/set-current endpoint."""

    def test_sqlite_rollback_restores_explicit_null_projection_from_canonical_v1(self, sqlite_client):
        client, db = sqlite_client
        component_id = "rollback-canonical-projection"

        created = client.post(
            "/components",
            json={
                "component_id": component_id,
                "component_type": "agent",
                "name": "Version one",
                "stage": "published",
                "config": {"id": component_id, "instructions": "v1"},
            },
        )
        assert created.status_code == 201

        version_two = client.post(
            f"/components/{component_id}/configs",
            json={
                "config": {
                    "id": component_id,
                    "name": "Version two",
                    "description": "Newer description",
                    "metadata": {"release": 2},
                    "instructions": "v2",
                },
                "stage": "published",
                **_guard(1, 1),
            },
        )
        assert version_two.status_code == 201

        rolled_back = client.post(
            f"/components/{component_id}/configs/1/set-current",
            json=_guard(2, 2),
        )

        assert rolled_back.status_code == 200
        assert rolled_back.json()["current_version"] == 1
        assert rolled_back.json()["name"] == "Version one"
        assert rolled_back.json().get("description") is None
        assert rolled_back.json().get("metadata") is None

        component = db.get_component(component_id)
        version_one = db.get_config(component_id, version=1)
        assert component is not None
        assert version_one is not None
        assert component["current_version"] == 1
        assert component["name"] == "Version one"
        assert component["description"] is None
        assert component["metadata"] is None
        assert version_one["config"]["name"] == "Version one"
        assert version_one["config"]["description"] is None
        assert version_one["config"]["metadata"] is None

    def test_sqlite_rollback_restores_projection_from_direct_agent_save(self, sqlite_client):
        client, db = sqlite_client
        component_id = "direct-save-projection"
        agent = Agent(
            id=component_id,
            name="Version one",
            description=None,
            metadata=None,
            model=OpenAIResponses(id="gpt-5.4"),
        )
        assert agent.save(db=db) == 1
        agent.name = "Version two"
        agent.description = "Newer description"
        agent.metadata = {"release": 2}
        assert agent.save(db=db) == 2

        rolled_back = client.post(
            f"/components/{component_id}/configs/1/set-current",
            json=_guard(2, 2),
        )

        assert rolled_back.status_code == 200
        assert rolled_back.json()["current_version"] == 1
        assert rolled_back.json()["name"] == "Version one"
        assert rolled_back.json().get("description") is None
        assert rolled_back.json().get("metadata") is None
        component = db.get_component(component_id)
        version_one = db.get_config(component_id, version=1)
        assert component is not None
        assert version_one is not None
        assert component["name"] == "Version one"
        assert component["description"] is None
        assert component["metadata"] is None
        assert version_one["config"]["name"] == "Version one"
        assert version_one["config"]["description"] is None
        assert version_one["config"]["metadata"] is None

    def test_set_current_config_success(self, client, mock_db):
        """Test set_current_config sets version as current."""
        mock_db.set_current_version.return_value = True
        mock_db.get_component.return_value = {
            "component_id": "agent-1",
            "name": "Agent 3",
            "description": "Current description",
            "metadata": {"release": 3},
            "component_type": "agent",
            "current_version": 3,
            "created_at": 1234567890,
        }
        mock_db.get_config.return_value = {
            "component_id": "agent-1",
            "version": 1,
            "config": {
                "name": "Agent 1",
                "description": "Restored description",
                "metadata": {"release": 1},
            },
            "stage": "published",
            "created_at": 1234567890,
        }

        response = client.post("/components/agent-1/configs/1/set-current", json=_guard(3, 3))

        assert response.status_code == 200
        data = response.json()
        assert data["current_version"] == 1
        assert data["name"] == "Agent 1"
        assert data["description"] == "Restored description"
        assert data["metadata"] == {"release": 1}
        mock_db.set_current_version.assert_called_once_with(
            "agent-1",
            version=1,
            guard=ComponentVersionGuard(latest_version=3, current_version=3),
            projection={
                "name": "Agent 1",
                "description": "Restored description",
                "metadata": {"release": 1},
            },
        )
        # The response is synthesized from the pre-mutation row and committed
        # projection, so it cannot observe a later mutation through a re-read.
        mock_db.get_component.assert_called_once_with("agent-1")
        mock_db.get_config.assert_called_once_with("agent-1", version=1)

    def test_set_current_config_requires_guard(self, client, mock_db):
        response = client.post("/components/agent-1/configs/1/set-current")

        assert response.status_code == 422
        mock_db.set_current_version.assert_not_called()

    def test_set_current_config_not_found(self, client, mock_db):
        """Test set_current_config returns 404 when version not found."""
        mock_db.get_component.return_value = {
            "component_id": "agent-1",
            "name": "Agent 1",
            "component_type": "agent",
            "current_version": 1,
            "created_at": 1234567890,
        }
        mock_db.get_config.return_value = None

        response = client.post("/components/agent-1/configs/999/set-current", json=_guard())

        assert response.status_code == 404
        mock_db.set_current_version.assert_not_called()

    def test_set_current_config_maps_stale_guard_to_conflict(self, client, mock_db):
        mock_db.get_component.return_value = {
            "component_id": "agent-1",
            "name": "Agent 1",
            "component_type": "agent",
            "current_version": 2,
            "created_at": 1234567890,
        }
        mock_db.get_config.return_value = {
            "component_id": "agent-1",
            "version": 1,
            "config": {"name": "Agent 1"},
            "stage": "published",
            "created_at": 1234567890,
        }
        mock_db.set_current_version.side_effect = ComponentVersionConflictError(
            "agent-1",
            expected=ComponentVersionGuard(latest_version=2, current_version=2),
            actual=ComponentVersionGuard(latest_version=3, current_version=2),
        )

        response = client.post("/components/agent-1/configs/1/set-current", json=_guard(2, 2))

        assert response.status_code == 409

    def test_set_current_config_handles_value_error(self, client, mock_db):
        """Test set_current_config returns 400 on ValueError."""
        mock_db.get_component.return_value = {
            "component_id": "agent-1",
            "name": "Agent 1",
            "component_type": "agent",
            "current_version": 1,
            "created_at": 1234567890,
        }
        mock_db.get_config.return_value = {
            "component_id": "agent-1",
            "version": 2,
            "config": {"name": "Agent 2"},
            "stage": "draft",
            "created_at": 1234567890,
        }
        mock_db.set_current_version.side_effect = ValueError("Version not published")

        response = client.post("/components/agent-1/configs/2/set-current", json=_guard())

        assert response.status_code == 400


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
