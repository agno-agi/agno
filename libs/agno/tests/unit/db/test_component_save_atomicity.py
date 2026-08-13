"""Regression tests for atomic component/config saves through core objects."""

from typing import Any, Dict, List, Optional

import pytest

from agno.agent.agent import Agent, get_agent_by_id, get_agents
from agno.db.base import (
    BaseDb,
    ComponentArchivedError,
    ComponentDependencyError,
    ComponentType,
    ComponentVersionConflictError,
    ComponentVersionGuard,
    ComponentVersionGuardRequiredError,
)
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
from agno.utils.string import generate_component_id_from_name
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

    def delete_component(self, component_id: str, hard_delete: bool = False) -> bool:
        return super().delete_component(component_id=component_id, hard_delete=hard_delete)


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


class _PublishBetweenLoadAndGuardSqliteDb(SqliteDb):
    """Publish after a load reads config but before it captures CAS state."""

    publish_before_next_get_component = False

    def get_component(
        self,
        component_id: str,
        component_type: Optional[ComponentType] = None,
        *,
        include_deleted: bool = False,
    ) -> Optional[Dict[str, Any]]:
        if self.publish_before_next_get_component:
            self.publish_before_next_get_component = False
            super().upsert_config(
                component_id,
                config={"id": component_id, "name": "Concurrent publication"},
                stage="published",
                guard=ComponentVersionGuard(latest_version=1, current_version=1),
                projection={"name": "Concurrent publication"},
            )
        return super().get_component(component_id, component_type, include_deleted=include_deleted)


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

    assert agent.delete(db=db) is True


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


def test_save_requires_explicit_restore_then_appends_history(tmp_path) -> None:
    db = SqliteDb(db_file=str(tmp_path / "explicit-restore-before-save.db"))
    agent = Agent(id="restorable-agent", name="Version one", description="Before archive", db=db)
    assert agent.save(stage="published") == 1
    assert agent.delete() is True

    agent.name = "Version two"
    agent.description = "After restore"
    with pytest.raises(ComponentArchivedError, match="restore it explicitly"):
        agent.save(stage="published")

    assert db.restore_component(
        "restorable-agent",
        guard=ComponentVersionGuard(latest_version=1, current_version=1),
        projection={"name": "Version one", "description": "Before archive", "metadata": None},
    )
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
    with pytest.raises(ComponentArchivedError, match="restore it explicitly"):
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
    child = Agent.load("child-agent", db=db)
    assert child is not None

    with pytest.raises(ComponentDependencyError):
        child.delete()

    assert child.delete(require_no_dependents=False) is True
    assert db.get_component("child-agent") is None


def test_draft_save_rejects_publish_after_captured_component_state(tmp_path) -> None:
    db = _PublishDuringReadSqliteDb(db_file=str(tmp_path / "publish-race.db"))
    agent = Agent(id="race-agent", name="Initial draft", db=db)
    assert agent.save(stage="draft") == 1

    agent.name = "Later draft"
    db.publish_during_next_get = True
    with pytest.raises(ComponentVersionConflictError):
        agent.save(stage="draft")

    component = db.get_component("race-agent")
    assert component is not None
    assert component["current_version"] == 2
    assert component["name"] == "Published concurrently"
    assert db.get_current_config("race-agent")["version"] == 2  # type: ignore[index]
    latest = db.get_latest_config("race-agent")
    assert latest is not None
    assert latest["version"] == 2
    assert latest["stage"] == "published"


def test_two_loaded_agents_cannot_overwrite_each_others_snapshot(tmp_path) -> None:
    db = SqliteDb(db_file=str(tmp_path / "stale-loaded-agent.db"))
    original = Agent(id="guarded-agent", name="Original", db=db)
    assert original.save() == 1

    first = Agent.load("guarded-agent", db=db)
    stale = Agent.load("guarded-agent", db=db)
    assert first is not None and stale is not None

    first.name = "Winner"
    assert first.save() == 2
    stale.name = "Stale loser"
    with pytest.raises(ComponentVersionConflictError):
        stale.save()

    current = db.get_current_config("guarded-agent")
    assert current is not None
    assert current["version"] == 2
    assert current["config"]["name"] == "Winner"


def test_loaded_team_and_workflow_saves_reject_stale_snapshots(tmp_path) -> None:
    db = SqliteDb(db_file=str(tmp_path / "stale-team-workflow.db"))
    team = Team(id="guarded-team", name="Team", members=[], db=db)
    workflow = Workflow(id="guarded-workflow", name="Workflow", db=db)
    assert team.save() == 1
    assert workflow.save() == 1

    first_team = Team.load("guarded-team", db=db)
    stale_team = Team.load("guarded-team", db=db)
    first_workflow = Workflow.load("guarded-workflow", db=db)
    stale_workflow = Workflow.load("guarded-workflow", db=db)
    assert first_team is not None and stale_team is not None
    assert first_workflow is not None and stale_workflow is not None

    first_team.name = "Winning team"
    assert first_team.save() == 2
    stale_team.name = "Stale team"
    with pytest.raises(ComponentVersionConflictError):
        stale_team.save()

    first_workflow.name = "Winning workflow"
    assert first_workflow.save() == 2
    stale_workflow.name = "Stale workflow"
    with pytest.raises(ComponentVersionConflictError):
        stale_workflow.save()


def test_stale_loaded_object_cannot_archive_newer_version(tmp_path) -> None:
    db = SqliteDb(db_file=str(tmp_path / "stale-delete.db"))
    assert Agent(id="stale-delete", name="Original", db=db).save() == 1
    writer = Agent.load("stale-delete", db=db)
    stale_deleter = Agent.load("stale-delete", db=db)
    assert writer is not None and stale_deleter is not None

    writer.name = "Newer"
    assert writer.save() == 2

    with pytest.raises(ComponentVersionConflictError):
        stale_deleter.delete()
    assert db.get_component("stale-delete") is not None


def test_public_delete_validates_component_type_inside_transaction(tmp_path) -> None:
    db = SqliteDb(db_file=str(tmp_path / "delete-type.db"))
    assert Team(id="shared-delete-id", name="Team", members=[], db=db).save() == 1
    wrong_type = Agent(id="shared-delete-id", name="Not the team", db=db)

    with pytest.raises(ValueError, match="has type team, not agent"):
        wrong_type.delete(guard=ComponentVersionGuard(latest_version=1, current_version=1))

    component = db.get_component("shared-delete-id")
    assert component is not None
    assert component["component_type"] == ComponentType.TEAM.value


def test_existing_id_requires_loaded_or_explicit_guard(tmp_path) -> None:
    db = SqliteDb(db_file=str(tmp_path / "guard-required.db"))
    assert Agent(id="guard-required", name="Original", db=db).save() == 1

    unattached = Agent(id="guard-required", name="Overwrite", db=db)
    with pytest.raises(ComponentVersionGuardRequiredError):
        unattached.save()


def test_captured_guard_cannot_be_reused_against_a_different_database(tmp_path) -> None:
    db_a = SqliteDb(db_file=str(tmp_path / "guard-db-a.db"))
    db_b = SqliteDb(db_file=str(tmp_path / "guard-db-b.db"))
    from_a = Agent(id="same-id", name="Database A", db=db_a)
    assert from_a.save() == 1
    assert Agent(id="same-id", name="Database B", db=db_b).save() == 1

    from_a.name = "Cross-db overwrite"
    with pytest.raises(ComponentVersionGuardRequiredError):
        from_a.save(db=db_b)

    assert db_b.get_current_config("same-id")["config"]["name"] == "Database B"


def test_captured_guard_distinguishes_independent_in_memory_databases() -> None:
    db_a = SqliteDb(db_url="sqlite://")
    db_b = SqliteDb(db_url="sqlite://")
    from_a = Agent(id="same-memory-id", name="Database A", db=db_a)
    assert from_a.save() == 1
    assert Agent(id="same-memory-id", name="Database B", db=db_b).save() == 1

    from_a.name = "Cross-db overwrite"
    with pytest.raises(ComponentVersionGuardRequiredError):
        from_a.save(db=db_b)

    assert db_b.get_current_config("same-memory-id")["config"]["name"] == "Database B"


def test_load_does_not_attach_fresh_guard_to_replaced_config_snapshot(tmp_path) -> None:
    db = _PublishBetweenLoadAndGuardSqliteDb(db_file=str(tmp_path / "load-guard-race.db"))
    assert Agent(id="load-race", name="Version one", db=db).save() == 1
    db.publish_before_next_get_component = True

    stale = Agent.load("load-race", db=db)
    assert stale is not None
    stale.name = "Must not overwrite"

    with pytest.raises(ComponentVersionGuardRequiredError):
        stale.save()
    assert db.get_current_config("load-race")["config"]["name"] == "Concurrent publication"


def test_load_of_published_snapshot_cannot_silently_overwrite_newer_draft(tmp_path) -> None:
    db = SqliteDb(db_file=str(tmp_path / "load-with-draft.db"))
    original = Agent(id="load-with-draft", name="Published", db=db)
    assert original.save() == 1
    assert original.save(stage="draft") == 2

    published = Agent.load("load-with-draft", db=db)
    assert published is not None
    assert published.name == "Published"
    published.name = "Must not skip the draft"

    with pytest.raises(ComponentVersionGuardRequiredError):
        published.save()
    assert db.get_latest_config("load-with-draft")["version"] == 2  # type: ignore[index]


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


def test_direct_component_saves_share_the_url_safe_name_id_contract(tmp_path) -> None:
    name = "R&D Jörg"
    expected = generate_component_id_from_name(name)
    agent = Agent(name=name, db=SqliteDb(db_file=str(tmp_path / "agent-id.db")))
    team = Team(name=name, members=[], db=SqliteDb(db_file=str(tmp_path / "team-id.db")))
    workflow = Workflow(name=name, db=SqliteDb(db_file=str(tmp_path / "workflow-id.db")))

    assert expected == "r-d-jörg"
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
