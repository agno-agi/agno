"""Regression tests for atomic component/config saves through core objects."""

from typing import Any, Dict, List, Optional

import pytest

from agno.agent.agent import Agent, get_agent_by_id, get_agents
from agno.db.base import BaseDb, ComponentDependencyError, ComponentType
from agno.db.sqlite import SqliteDb
from agno.os.utils import (
    get_agent_by_id as get_runtime_agent_by_id,
)
from agno.os.utils import (
    get_team_by_id as get_runtime_team_by_id,
)
from agno.os.utils import (
    get_workflow_by_id as get_runtime_workflow_by_id,
)
from agno.team.team import Team, get_team_by_id, get_teams
from agno.utils.string import generate_id_from_name
from agno.workflow.workflow import Workflow, get_workflow_by_id, get_workflows


class _LegacyComponentSqliteDb(SqliteDb):
    """Custom adapter exposing only the exact pre-2.9 catalog signatures."""

    supports_component_persistence = False
    component_catalog_api_version = 1

    def get_component(
        self,
        component_id: str,
        component_type: Optional[ComponentType] = None,
    ) -> Optional[Dict[str, Any]]:
        return super().get_component(component_id, component_type)

    def upsert_config(
        self,
        component_id: str,
        config: Optional[Dict[str, Any]] = None,
        version: Optional[int] = None,
        label: Optional[str] = None,
        stage: Optional[str] = None,
        notes: Optional[str] = None,
        links: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        return super().upsert_config(
            component_id=component_id,
            config=config,
            version=version,
            label=label,
            stage=stage,
            notes=notes,
            links=links,
        )

    def create_component_with_config(self, *args, **kwargs):
        raise AssertionError("catalog API v1 must not probe the v2 atomic primitive")


class _BrokenAtomicSqliteDb(SqliteDb):
    """An opted-in adapter must not silently downgrade atomic creation."""

    def create_component_with_config(self, *args, **kwargs):
        raise NotImplementedError


class _PublishDuringReadSqliteDb(SqliteDb):
    """Inject a publication after save's initial read to reproduce the race."""

    publish_during_next_get = False

    def get_component(
        self,
        component_id: str,
        component_type: Optional[ComponentType] = None,
        *,
        include_deleted: bool = False,
    ) -> Optional[Dict[str, Any]]:
        component = super().get_component(
            component_id,
            component_type,
            include_deleted=include_deleted,
        )
        if self.publish_during_next_get and component is not None:
            self.publish_during_next_get = False
            super().upsert_config(
                component_id,
                config={"id": component_id, "name": "Published concurrently"},
                stage="published",
                projection={"name": "Published concurrently"},
            )
        return component


class _ReplaceDuringReadSqliteDb(SqliteDb):
    """Replace an ID after save's optimistic read to reproduce identity ABA."""

    replace_during_next_get = False

    def get_component(
        self,
        component_id: str,
        component_type: Optional[ComponentType] = None,
        *,
        include_deleted: bool = False,
    ) -> Optional[Dict[str, Any]]:
        component = super().get_component(
            component_id,
            component_type,
            include_deleted=include_deleted,
        )
        if self.replace_during_next_get and component is not None:
            self.replace_during_next_get = False
            super().delete_component(component_id, hard_delete=True, require_no_dependents=False)
            super().create_component_with_config(
                component_id=component_id,
                component_type=ComponentType.TEAM,
                name="Replacement team",
                config={"name": "Replacement team", "members": []},
                stage="published",
            )
        return component


def _assert_no_component_or_configs(db: SqliteDb, component_id: str) -> None:
    assert db.get_component(component_id, include_deleted=True) is None
    assert db.list_configs(component_id, include_config=True) == []


def _assert_original_projection_and_config(db: SqliteDb, component_id: str) -> None:
    component = db.get_component(component_id)
    assert component is not None
    assert component["name"] == "Version one"
    assert component["description"] == "Original description"
    assert component["metadata"] == {"revision": 1}
    assert component["current_version"] == 1

    configs = db.list_configs(component_id, include_config=True)
    assert len(configs) == 1
    assert configs[0]["version"] == 1
    assert configs[0]["label"] == "stable"
    assert configs[0]["config"]["name"] == "Version one"
    assert configs[0]["config"]["description"] == "Original description"
    assert configs[0]["config"]["metadata"] == {"revision": 1}


def test_agent_first_save_invalid_stage_leaves_no_orphan(tmp_path) -> None:
    db = SqliteDb(db_file=str(tmp_path / "agent-invalid-stage.db"))
    agent = Agent(id="atomic-agent", name="Agent")

    with pytest.raises(ValueError, match="Invalid stage"):
        agent.save(db=db, stage="invalid")

    _assert_no_component_or_configs(db, "atomic-agent")


def test_team_first_save_invalid_stage_leaves_no_orphan(tmp_path) -> None:
    db = SqliteDb(db_file=str(tmp_path / "team-invalid-stage.db"))
    team = Team(id="atomic-team", name="Team", members=[])

    with pytest.raises(ValueError, match="Invalid stage"):
        team.save(db=db, stage="invalid")

    _assert_no_component_or_configs(db, "atomic-team")


def test_workflow_first_save_invalid_stage_leaves_no_orphan(tmp_path) -> None:
    db = SqliteDb(db_file=str(tmp_path / "workflow-invalid-stage.db"))
    workflow = Workflow(id="atomic-workflow", name="Workflow")

    assert workflow.save(db=db, stage="invalid") is None

    _assert_no_component_or_configs(db, "atomic-workflow")


def test_agent_duplicate_label_does_not_drift_published_projection(tmp_path) -> None:
    db = SqliteDb(db_file=str(tmp_path / "agent-duplicate-label.db"))
    agent = Agent(
        id="atomic-agent",
        name="Version one",
        description="Original description",
        metadata={"revision": 1},
    )
    assert agent.save(db=db, stage="published", label="stable") == 1

    agent.name = "Version two"
    agent.description = "Changed description"
    agent.metadata = {"revision": 2}
    with pytest.raises(ValueError, match="Label 'stable' already exists"):
        agent.save(db=db, stage="published", label="stable")

    _assert_original_projection_and_config(db, "atomic-agent")


def test_team_duplicate_label_does_not_drift_published_projection(tmp_path) -> None:
    db = SqliteDb(db_file=str(tmp_path / "team-duplicate-label.db"))
    team = Team(
        id="atomic-team",
        name="Version one",
        description="Original description",
        metadata={"revision": 1},
        members=[],
    )
    assert team.save(db=db, stage="published", label="stable") == 1

    team.name = "Version two"
    team.description = "Changed description"
    team.metadata = {"revision": 2}
    with pytest.raises(ValueError, match="Label 'stable' already exists"):
        team.save(db=db, stage="published", label="stable")

    _assert_original_projection_and_config(db, "atomic-team")


def test_workflow_duplicate_label_does_not_drift_published_projection(tmp_path) -> None:
    db = SqliteDb(db_file=str(tmp_path / "workflow-duplicate-label.db"))
    workflow = Workflow(
        id="atomic-workflow",
        name="Version one",
        description="Original description",
        metadata={"revision": 1},
    )
    assert workflow.save(db=db, stage="published", label="stable") == 1

    workflow.name = "Version two"
    workflow.description = "Changed description"
    workflow.metadata = {"revision": 2}
    assert workflow.save(db=db, stage="published", label="stable") is None

    _assert_original_projection_and_config(db, "atomic-workflow")


def test_first_save_falls_back_for_legacy_custom_component_adapter(tmp_path) -> None:
    db = _LegacyComponentSqliteDb(db_file=str(tmp_path / "legacy-component-adapter.db"))
    agent = Agent(
        id="legacy-agent",
        name="Legacy adapter agent",
        description="Saved through the compatibility path",
    )

    assert agent.save(db=db, stage="published") == 1

    component = db.get_component("legacy-agent")
    config = db.get_config("legacy-agent", version=1)
    assert component is not None
    assert component["name"] == "Legacy adapter agent"
    assert component["current_version"] == 1
    assert config is not None and config["stage"] == "published"


def test_base_bulk_read_fallback_preserves_legacy_scalar_signatures(tmp_path) -> None:
    db = _LegacyComponentSqliteDb(db_file=str(tmp_path / "legacy-bulk-read-adapter.db"))
    agent = Agent(id="legacy-bulk-agent", name="Legacy bulk agent")
    assert agent.save(db=db, stage="published") == 1

    components = BaseDb.get_components(
        db,
        {"legacy-bulk-agent", "missing-agent"},
        component_type=ComponentType.AGENT,
    )
    latest = BaseDb.get_latest_configs(db, {"legacy-bulk-agent", "missing-agent"})

    assert [component["component_id"] for component in components] == ["legacy-bulk-agent"]
    assert set(latest) == {"legacy-bulk-agent", "missing-agent"}
    assert latest["legacy-bulk-agent"] is not None
    assert latest["legacy-bulk-agent"]["version"] == 1
    assert latest["missing-agent"] is None


def test_opted_in_atomic_adapter_cannot_silently_use_legacy_fallback(tmp_path) -> None:
    db = _BrokenAtomicSqliteDb(db_file=str(tmp_path / "broken-atomic-adapter.db"))
    agent = Agent(id="broken-atomic-agent", name="Broken atomic adapter")

    with pytest.raises(NotImplementedError):
        agent.save(db=db, stage="published")

    _assert_no_component_or_configs(db, "broken-atomic-agent")


def test_draft_only_projection_tracks_latest_draft_then_freezes_after_publish(tmp_path) -> None:
    db = SqliteDb(db_file=str(tmp_path / "draft-projection.db"))
    agent = Agent(
        id="draft-projection-agent",
        name="Draft one",
        description="First draft",
        metadata={"revision": 1},
    )
    assert agent.save(db=db, stage="draft") == 1

    agent.name = "Draft two"
    agent.description = "Second draft"
    agent.metadata = {"revision": 2}
    assert agent.save(db=db, stage="draft") == 2

    component = db.get_component("draft-projection-agent")
    assert component is not None
    assert component["current_version"] is None
    assert component["name"] == "Draft two"
    assert component["description"] == "Second draft"
    assert component["metadata"] == {"revision": 2}

    agent.name = "Published"
    agent.description = "Published description"
    agent.metadata = {"revision": 3}
    assert agent.save(db=db, stage="published") == 3

    agent.name = "Unpublished draft"
    agent.description = "Must not leak"
    agent.metadata = {"revision": 4}
    assert agent.save(db=db, stage="draft") == 4

    component = db.get_component("draft-projection-agent")
    assert component is not None
    assert component["current_version"] == 3
    assert component["name"] == "Published"
    assert component["description"] == "Published description"
    assert component["metadata"] == {"revision": 3}


def test_save_restores_archived_component_and_appends_history(tmp_path) -> None:
    db = SqliteDb(db_file=str(tmp_path / "restore-on-save.db"))
    agent = Agent(id="restorable-agent", name="Version one", description="Before archive", db=db)
    assert agent.save(stage="published") == 1
    assert agent.delete() is True

    agent.name = "Version two"
    agent.description = "After restore"
    assert agent.save(stage="published") == 2

    component = db.get_component("restorable-agent")
    assert component is not None
    assert component["deleted_at"] is None
    assert component["current_version"] == 2
    assert component["name"] == "Version two"
    assert [row["version"] for row in db.list_configs("restorable-agent")] == [2, 1]


def test_failed_save_does_not_restore_archived_component(tmp_path) -> None:
    db = SqliteDb(db_file=str(tmp_path / "failed-restore-on-save.db"))
    agent = Agent(id="archived-agent", name="Version one", db=db)
    assert agent.save(stage="published", label="stable") == 1
    assert agent.delete() is True

    agent.name = "Rejected version"
    with pytest.raises(ValueError, match="Label 'stable' already exists"):
        agent.save(stage="published", label="stable")

    assert db.get_component("archived-agent") is None
    archived = db.get_component("archived-agent", include_deleted=True)
    assert archived is not None
    assert archived["deleted_at"] is not None
    latest = db.get_latest_config("archived-agent", include_deleted=True)
    assert latest is not None
    assert latest["version"] == 1


def test_public_delete_dependency_check_has_explicit_escape_hatch(tmp_path) -> None:
    db = SqliteDb(db_file=str(tmp_path / "delete-dependency.db"))
    db.create_component_with_config(
        component_id="child-agent",
        component_type=ComponentType.AGENT,
        name="Child",
        config={"name": "Child"},
        stage="published",
    )
    db.create_component_with_config(
        component_id="parent-team",
        component_type=ComponentType.TEAM,
        name="Parent",
        config={"name": "Parent"},
        stage="published",
        links=[
            {
                "link_kind": "member",
                "link_key": "member_0",
                "child_component_id": "child-agent",
                "child_version": 1,
                "position": 0,
            }
        ],
    )
    child = Agent(id="child-agent", db=db)

    with pytest.raises(ComponentDependencyError):
        child.delete()

    assert child.delete(require_no_dependents=False) is True
    assert db.get_component("child-agent") is None


def test_draft_save_survives_publish_after_initial_component_read(tmp_path) -> None:
    db = _PublishDuringReadSqliteDb(db_file=str(tmp_path / "publish-race.db"))
    agent = Agent(id="race-agent", name="Initial draft", db=db)
    assert agent.save(stage="draft") == 1

    agent.name = "Later draft"
    db.publish_during_next_get = True
    assert agent.save(stage="draft") == 3

    component = db.get_component("race-agent")
    assert component is not None
    assert component["current_version"] == 2
    assert component["name"] == "Published concurrently"
    assert db.get_current_config("race-agent")["version"] == 2  # type: ignore[index]
    latest = db.get_latest_config("race-agent")
    assert latest is not None
    assert latest["version"] == 3
    assert latest["stage"] == "draft"
    assert latest["config"]["name"] == "Later draft"


def test_save_rejects_component_type_replacement_after_initial_read(tmp_path) -> None:
    db = _ReplaceDuringReadSqliteDb(db_file=str(tmp_path / "component-type-race.db"))
    agent = Agent(id="replaced-component", name="Original agent", db=db)
    assert agent.save(stage="published") == 1

    db.replace_during_next_get = True
    agent.name = "Must not reach the replacement"
    with pytest.raises(ValueError, match="has type team, not agent"):
        agent.save(stage="published")

    component = db.get_component("replaced-component")
    assert component is not None
    assert component["component_type"] == ComponentType.TEAM.value
    assert component["name"] == "Replacement team"
    assert component["current_version"] == 1
    assert [row["version"] for row in db.list_configs("replaced-component")] == [1]


def test_direct_component_saves_share_the_historical_name_id_contract(tmp_path) -> None:
    name = "R&D Jörg"
    expected = generate_id_from_name(name)
    agent = Agent(name=name, db=SqliteDb(db_file=str(tmp_path / "agent-id.db")))
    team = Team(name=name, members=[], db=SqliteDb(db_file=str(tmp_path / "team-id.db")))
    workflow = Workflow(name=name, db=SqliteDb(db_file=str(tmp_path / "workflow-id.db")))

    assert expected == "r&d-jörg"
    assert agent.save(stage="draft") == 1
    assert team.save(stage="draft") == 1
    assert workflow.save(stage="draft") == 1
    assert agent.id == expected
    assert team.id == expected
    assert workflow.id == expected


def test_draft_only_components_load_list_and_read_but_do_not_runtime_resolve(tmp_path) -> None:
    db = SqliteDb(db_file=str(tmp_path / "draft-read-contract.db"))
    agent = Agent(id="draft-agent", name="Draft agent", db=db)
    team = Team(id="draft-team", name="Draft team", members=[], db=db)
    workflow = Workflow(id="draft-workflow", name="Draft workflow", db=db)
    assert agent.save(stage="draft") == 1
    assert team.save(stage="draft") == 1
    assert workflow.save(stage="draft") == 1

    assert Agent.load("draft-agent", db=db) is not None
    assert Team.load("draft-team", db=db) is not None
    assert Workflow.load("draft-workflow", db=db) is not None

    assert get_agent_by_id(db, "draft-agent") is not None
    assert get_team_by_id(db, "draft-team") is not None
    assert get_workflow_by_id(db, "draft-workflow") is not None

    assert [item.id for item in get_agents(db)] == ["draft-agent"]
    assert [item.id for item in get_teams(db)] == ["draft-team"]
    assert [item.id for item in get_workflows(db)] == ["draft-workflow"]

    assert get_runtime_agent_by_id("draft-agent", db=db) is None
    assert get_runtime_team_by_id("draft-team", db=db) is None
    assert get_runtime_workflow_by_id("draft-workflow", db=db) is None
