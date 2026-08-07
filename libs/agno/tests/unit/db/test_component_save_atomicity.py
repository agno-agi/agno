"""Regression tests for atomic component/config saves through core objects."""

import pytest

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.team.team import Team
from agno.workflow.workflow import Workflow


class _LegacyComponentSqliteDb(SqliteDb):
    """Stand-in for a custom adapter that has not added atomic first-save."""

    supports_component_persistence = False

    def create_component_with_config(self, *args, **kwargs):
        raise NotImplementedError


class _BrokenAtomicSqliteDb(SqliteDb):
    """An opted-in adapter must not silently downgrade atomic creation."""

    def create_component_with_config(self, *args, **kwargs):
        raise NotImplementedError


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
