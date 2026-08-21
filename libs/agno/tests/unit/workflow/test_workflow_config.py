"""
Unit tests for Workflow configuration serialization and persistence.

Tests cover:
- to_dict(): Serialization of workflow to dictionary
- from_dict(): Deserialization of workflow from dictionary
- save(): Saving workflow to database (including steps with agents/teams)
- load(): Loading workflow from database
- delete(): Deleting workflow from database
- get_workflow_by_id(): Helper function to get workflow by ID
- get_workflows(): Helper function to get all workflows
"""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from agno.db.base import BaseDb, ComponentType
from agno.registry import Registry
from agno.workflow.workflow import Workflow, get_workflow_by_id, get_workflows

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
    """Create a mock database instance that passes isinstance(db, BaseDb)."""
    MockDbClass = _create_mock_db_class()
    db = MockDbClass()

    # Configure common mock methods
    db.upsert_component = MagicMock()
    db.upsert_config = MagicMock(return_value={"version": 1})
    db.delete_component = MagicMock(return_value=True)
    db.get_config = MagicMock()
    db.list_components = MagicMock()
    db.get_links = MagicMock()
    db.to_dict = MagicMock(return_value={"type": "postgres", "id": "test-db"})

    return db


@pytest.fixture
def basic_workflow():
    """Create a basic workflow for testing."""
    return Workflow(
        id="test-workflow",
        name="Test Workflow",
        description="A test workflow for unit testing",
    )


@pytest.fixture
def workflow_with_settings():
    """Create a workflow with various settings configured."""
    return Workflow(
        id="settings-workflow",
        name="Settings Workflow",
        description="Workflow with many settings",
        debug_mode=True,
        stream_events=True,
        store_events=True,
        add_workflow_history_to_steps=True,
        num_history_runs=5,
    )


@pytest.fixture
def sample_workflow_config() -> Dict[str, Any]:
    """Sample workflow configuration dictionary."""
    return {
        "id": "sample-workflow",
        "name": "Sample Workflow",
        "description": "A sample workflow",
        "debug_mode": False,
        "telemetry": True,
    }


# =============================================================================
# to_dict() Tests
# =============================================================================


class TestWorkflowToDict:
    """Tests for Workflow.to_dict() method."""

    def test_to_dict_basic_workflow(self, basic_workflow):
        """Test to_dict with a basic workflow."""
        config = basic_workflow.to_dict()

        assert config["id"] == "test-workflow"
        assert config["name"] == "Test Workflow"
        assert config["description"] == "A test workflow for unit testing"

    def test_to_dict_with_settings(self, workflow_with_settings):
        """Test to_dict preserves all settings."""
        config = workflow_with_settings.to_dict()

        assert config["id"] == "settings-workflow"
        assert config["name"] == "Settings Workflow"
        assert config["description"] == "Workflow with many settings"
        assert config["debug_mode"] is True
        assert config["stream_events"] is True
        assert config["store_events"] is True
        assert config["add_workflow_history_to_steps"] is True
        assert config["num_history_runs"] == 5

    def test_to_dict_with_db(self, basic_workflow, mock_db):
        """Test to_dict includes database configuration."""
        basic_workflow.db = mock_db
        config = basic_workflow.to_dict()

        assert "db" in config
        assert config["db"] == {"type": "postgres", "id": "test-db"}

    def test_to_dict_with_metadata(self):
        """Test to_dict includes metadata."""
        workflow = Workflow(
            id="metadata-workflow",
            metadata={"version": "1.0", "workflow_type": "etl"},
        )
        config = workflow.to_dict()

        assert config["metadata"] == {"version": "1.0", "workflow_type": "etl"}

    def test_to_dict_with_user_and_session(self):
        """Test to_dict includes user and session settings."""
        workflow = Workflow(
            id="session-workflow",
            user_id="user-123",
            session_id="session-456",
        )
        config = workflow.to_dict()

        assert config["user_id"] == "user-123"
        assert config["session_id"] == "session-456"

    def test_to_dict_includes_default_settings(self):
        """Test to_dict includes certain default settings."""
        workflow = Workflow(id="defaults-workflow")
        config = workflow.to_dict()

        # These settings are always included
        assert "debug_mode" in config
        assert "telemetry" in config
        assert "add_workflow_history_to_steps" in config
        assert "num_history_runs" in config

    def test_to_dict_with_steps(self):
        """Test to_dict serializes steps."""
        from agno.workflow.workflow import Step

        mock_step = MagicMock(spec=Step)
        mock_step.to_dict.return_value = {"name": "step-1", "executor_id": "agent-1"}

        workflow = Workflow(
            id="steps-workflow",
            steps=[mock_step],
        )
        config = workflow.to_dict()

        assert "steps" in config
        assert len(config["steps"]) == 1
        assert config["steps"][0] == {"name": "step-1", "executor_id": "agent-1"}


# =============================================================================
# from_dict() Tests
# =============================================================================


class TestWorkflowFromDict:
    """Tests for Workflow.from_dict() method."""

    def test_from_dict_basic(self, sample_workflow_config):
        """Test from_dict creates workflow with basic config."""
        workflow = Workflow.from_dict(sample_workflow_config)

        assert workflow.id == "sample-workflow"
        assert workflow.name == "Sample Workflow"
        assert workflow.description == "A sample workflow"
        assert workflow.debug_mode is False
        assert workflow.telemetry is True

    def test_from_dict_preserves_settings(self):
        """Test from_dict preserves all settings."""
        config = {
            "id": "full-workflow",
            "name": "Full Workflow",
            "debug_mode": True,
            "stream_events": True,
            "store_events": True,
            "add_workflow_history_to_steps": True,
            "num_history_runs": 10,
        }

        workflow = Workflow.from_dict(config)

        assert workflow.debug_mode is True
        assert workflow.stream_events is True
        assert workflow.store_events is True
        assert workflow.add_workflow_history_to_steps is True
        assert workflow.num_history_runs == 10

    def test_from_dict_with_db_postgres(self):
        """Test from_dict reconstructs PostgresDb."""
        config = {
            "id": "db-workflow",
            "db": {"type": "postgres", "db_url": "postgresql://localhost/test"},
        }

        with patch("agno.db.postgres.PostgresDb.from_dict") as mock_from_dict:
            mock_db = MagicMock()
            mock_from_dict.return_value = mock_db

            workflow = Workflow.from_dict(config)

            mock_from_dict.assert_called_once()
            assert workflow.db == mock_db

    def test_from_dict_with_db_sqlite(self):
        """Test from_dict reconstructs SqliteDb."""
        config = {
            "id": "sqlite-workflow",
            "db": {"type": "sqlite", "db_file": "/tmp/test.db"},
        }

        with patch("agno.db.sqlite.SqliteDb.from_dict") as mock_from_dict:
            mock_db = MagicMock()
            mock_from_dict.return_value = mock_db

            workflow = Workflow.from_dict(config)

            mock_from_dict.assert_called_once()
            assert workflow.db == mock_db

    def test_from_dict_with_steps(self):
        """Test from_dict reconstructs steps."""
        config = {
            "id": "steps-workflow",
            "steps": [{"name": "step-1"}],
        }

        with patch("agno.workflow.workflow.Step.from_dict") as mock_step_from_dict:
            mock_step = MagicMock()
            mock_step_from_dict.return_value = mock_step

            workflow = Workflow.from_dict(config)

            mock_step_from_dict.assert_called_once()
            assert workflow.steps == [mock_step]

    def test_from_dict_roundtrip(self, workflow_with_settings):
        """Test that to_dict -> from_dict preserves workflow configuration."""
        config = workflow_with_settings.to_dict()
        reconstructed = Workflow.from_dict(config)

        assert reconstructed.id == workflow_with_settings.id
        assert reconstructed.name == workflow_with_settings.name
        assert reconstructed.description == workflow_with_settings.description
        assert reconstructed.debug_mode == workflow_with_settings.debug_mode
        assert reconstructed.stream_events == workflow_with_settings.stream_events


# =============================================================================
# save() Tests
# =============================================================================


class TestWorkflowSave:
    """Tests for Workflow.save() method."""

    def test_save_calls_upsert_component(self, basic_workflow, mock_db):
        """Test save calls upsert_component with correct parameters."""
        mock_db.upsert_config.return_value = {"version": 1}

        basic_workflow.db = mock_db
        version = basic_workflow.save()

        mock_db.upsert_component.assert_called_once_with(
            component_id="test-workflow",
            component_type=ComponentType.WORKFLOW,
            name="Test Workflow",
            description="A test workflow for unit testing",
            metadata=None,
        )
        assert version == 1

    def test_save_calls_upsert_config(self, basic_workflow, mock_db):
        """Test save calls upsert_config with workflow config."""
        mock_db.upsert_config.return_value = {"version": 2}

        basic_workflow.db = mock_db
        version = basic_workflow.save()

        mock_db.upsert_config.assert_called_once()
        call_args = mock_db.upsert_config.call_args
        assert call_args.kwargs["component_id"] == "test-workflow"
        assert "config" in call_args.kwargs
        assert version == 2

    def test_save_with_explicit_db(self, basic_workflow, mock_db):
        """Test save uses explicitly provided db."""
        mock_db.upsert_config.return_value = {"version": 1}

        version = basic_workflow.save(db=mock_db)

        mock_db.upsert_component.assert_called_once()
        mock_db.upsert_config.assert_called_once()
        assert version == 1

    def test_save_with_label(self, basic_workflow, mock_db):
        """Test save passes label to upsert_config."""
        mock_db.upsert_config.return_value = {"version": 1}

        basic_workflow.db = mock_db
        basic_workflow.save(label="production")

        call_args = mock_db.upsert_config.call_args
        assert call_args.kwargs["label"] == "production"

    def test_save_with_stage(self, basic_workflow, mock_db):
        """Test save passes stage to upsert_config."""
        mock_db.upsert_config.return_value = {"version": 1}

        basic_workflow.db = mock_db
        basic_workflow.save(stage="draft")

        call_args = mock_db.upsert_config.call_args
        assert call_args.kwargs["stage"] == "draft"

    def test_save_with_notes(self, basic_workflow, mock_db):
        """Test save passes notes to upsert_config."""
        mock_db.upsert_config.return_value = {"version": 1}

        basic_workflow.db = mock_db
        basic_workflow.save(notes="Initial version")

        call_args = mock_db.upsert_config.call_args
        assert call_args.kwargs["notes"] == "Initial version"

    def test_save_without_db_raises_error(self, basic_workflow):
        """Test save raises error when no db is available."""
        with pytest.raises(ValueError, match="Db not initialized or provided"):
            basic_workflow.save()

    def test_save_with_steps_saves_agents(self, mock_db):
        """Test save saves agent executors in steps."""
        from agno.agent.agent import Agent
        from agno.workflow.workflow import Step

        mock_db.upsert_config.return_value = {"version": 1}

        mock_agent = MagicMock(spec=Agent)
        mock_agent.id = "step-agent"
        mock_agent.save.return_value = 3

        mock_step = MagicMock(spec=Step)
        mock_step.agent = mock_agent
        mock_step.team = None
        mock_step.to_dict.return_value = {"name": "step-1"}
        mock_step.get_links.return_value = [{"child_component_id": "step-agent", "link_kind": "executor"}]

        workflow = Workflow(
            id="agent-workflow",
            name="Agent Workflow",
            steps=[mock_step],
            db=mock_db,
        )
        workflow.save()

        # Agent should be saved
        mock_agent.save.assert_called_once()

    def test_save_returns_none_on_error(self, basic_workflow, mock_db):
        """Test save returns None when database operation fails."""
        mock_db.upsert_component.side_effect = Exception("Database error")

        basic_workflow.db = mock_db
        version = basic_workflow.save()

        assert version is None


# =============================================================================
# load() Tests
# =============================================================================


class TestWorkflowLoad:
    """Tests for Workflow.load() class method."""

    def test_load_returns_workflow(self, mock_db, sample_workflow_config):
        """Test load returns a workflow from database."""
        mock_db.get_config.return_value = {"config": sample_workflow_config}

        workflow = Workflow.load(id="sample-workflow", db=mock_db)

        assert workflow is not None
        assert workflow.id == "sample-workflow"
        assert workflow.name == "Sample Workflow"

    def test_load_with_version(self, mock_db):
        """Test load retrieves specific version."""
        mock_db.get_config.return_value = {"config": {"id": "versioned-workflow", "name": "V2 Workflow"}}

        Workflow.load(id="versioned-workflow", db=mock_db, version=2)

        mock_db.get_config.assert_called_once_with(component_id="versioned-workflow", label=None, version=2)

    def test_load_with_label(self, mock_db):
        """Test load retrieves labeled version."""
        mock_db.get_config.return_value = {"config": {"id": "labeled-workflow", "name": "Production Workflow"}}

        Workflow.load(id="labeled-workflow", db=mock_db, label="production")

        mock_db.get_config.assert_called_once_with(component_id="labeled-workflow", label="production", version=None)

    def test_load_returns_none_when_not_found(self, mock_db):
        """Test load returns None when workflow not found."""
        mock_db.get_config.return_value = None

        workflow = Workflow.load(id="nonexistent-workflow", db=mock_db)

        assert workflow is None

    def test_load_returns_none_when_config_missing(self, mock_db):
        """Test load returns None when config is missing."""
        mock_db.get_config.return_value = {"config": None}

        workflow = Workflow.load(id="empty-config-workflow", db=mock_db)

        assert workflow is None

    def test_load_sets_db_on_workflow(self, mock_db):
        """Test load sets db attribute on returned workflow."""
        mock_db.get_config.return_value = {"config": {"id": "db-workflow", "name": "DB Workflow"}}

        workflow = Workflow.load(id="db-workflow", db=mock_db)

        assert workflow is not None
        assert workflow.db == mock_db


# =============================================================================
# delete() Tests
# =============================================================================


class TestWorkflowDelete:
    """Tests for Workflow.delete() method."""

    def test_delete_calls_delete_component(self, basic_workflow, mock_db):
        """Test delete calls delete_component."""
        mock_db.delete_component.return_value = True

        basic_workflow.db = mock_db
        result = basic_workflow.delete()

        mock_db.delete_component.assert_called_once_with(component_id="test-workflow", hard_delete=False)
        assert result is True

    def test_delete_with_hard_delete(self, basic_workflow, mock_db):
        """Test delete with hard_delete flag."""
        mock_db.delete_component.return_value = True

        basic_workflow.db = mock_db
        result = basic_workflow.delete(hard_delete=True)

        mock_db.delete_component.assert_called_once_with(component_id="test-workflow", hard_delete=True)
        assert result is True

    def test_delete_with_explicit_db(self, basic_workflow, mock_db):
        """Test delete uses explicitly provided db."""
        mock_db.delete_component.return_value = True

        result = basic_workflow.delete(db=mock_db)

        mock_db.delete_component.assert_called_once()
        assert result is True

    def test_delete_without_db_raises_error(self, basic_workflow):
        """Test delete raises error when no db is available."""
        with pytest.raises(ValueError, match="Db not initialized or provided"):
            basic_workflow.delete()

    def test_delete_returns_false_on_failure(self, basic_workflow, mock_db):
        """Test delete returns False when operation fails."""
        mock_db.delete_component.return_value = False

        basic_workflow.db = mock_db
        result = basic_workflow.delete()

        assert result is False


# =============================================================================
# get_workflow_by_id() Tests
# =============================================================================


class TestGetWorkflowById:
    """Tests for get_workflow_by_id() helper function."""

    def test_get_workflow_by_id_returns_workflow(self, mock_db):
        """Test get_workflow_by_id returns workflow from database."""
        mock_db.get_config.return_value = {
            "config": {"id": "found-workflow", "name": "Found Workflow"},
            "version": 1,
        }
        mock_db.get_links.return_value = []

        workflow = get_workflow_by_id(db=mock_db, id="found-workflow")

        assert workflow is not None
        assert workflow.id == "found-workflow"
        assert workflow.name == "Found Workflow"

    def test_get_workflow_by_id_with_version(self, mock_db):
        """Test get_workflow_by_id retrieves specific version."""
        mock_db.get_config.return_value = {
            "config": {"id": "versioned", "name": "V3"},
            "version": 3,
        }
        mock_db.get_links.return_value = []

        get_workflow_by_id(db=mock_db, id="versioned", version=3)

        mock_db.get_config.assert_called_once_with(component_id="versioned", version=3, label=None)

    def test_get_workflow_by_id_with_label(self, mock_db):
        """Test get_workflow_by_id retrieves labeled version."""
        mock_db.get_config.return_value = {
            "config": {"id": "labeled", "name": "Staging"},
            "version": 2,
        }
        mock_db.get_links.return_value = []

        get_workflow_by_id(db=mock_db, id="labeled", label="staging")

        mock_db.get_config.assert_called_once_with(component_id="labeled", version=None, label="staging")

    def test_get_workflow_by_id_fetches_links(self, mock_db):
        """Test get_workflow_by_id fetches links for the workflow version."""
        mock_db.get_config.return_value = {
            "config": {"id": "linked-workflow", "name": "Linked"},
            "version": 5,
        }
        mock_db.get_links.return_value = [{"child_component_id": "agent-1"}]

        get_workflow_by_id(db=mock_db, id="linked-workflow")

        mock_db.get_links.assert_called_once_with(component_id="linked-workflow", version=5)

    def test_get_workflow_by_id_returns_none_when_not_found(self, mock_db):
        """Test get_workflow_by_id returns None when not found."""
        mock_db.get_config.return_value = None

        workflow = get_workflow_by_id(db=mock_db, id="missing")

        assert workflow is None

    def test_get_workflow_by_id_sets_db(self, mock_db):
        """Test get_workflow_by_id sets db on returned workflow via registry."""
        # The db is set via registry lookup when config contains a serialized db reference
        mock_db.id = "test-db"
        mock_db.get_config.return_value = {
            "config": {
                "id": "db-workflow",
                "name": "DB Workflow",
                "db": {"type": "postgres", "id": "test-db"},
            },
            "version": 1,
        }
        mock_db.get_links.return_value = []

        # Create registry with the mock db registered
        registry = Registry(dbs=[mock_db])

        workflow = get_workflow_by_id(db=mock_db, id="db-workflow", registry=registry)

        assert workflow is not None
        assert workflow.db == mock_db

    def test_get_workflow_by_id_handles_error(self, mock_db):
        """Test get_workflow_by_id returns None on error."""
        mock_db.get_config.side_effect = Exception("DB error")

        workflow = get_workflow_by_id(db=mock_db, id="error-workflow")

        assert workflow is None


# =============================================================================
# get_workflows() Tests
# =============================================================================


class TestGetWorkflows:
    """Tests for get_workflows() helper function."""

    def test_get_workflows_returns_list(self, mock_db):
        """Test get_workflows returns list of workflows."""
        mock_db.list_components.return_value = (
            [
                {"component_id": "workflow-1"},
                {"component_id": "workflow-2"},
            ],
            None,
        )
        mock_db.get_config.side_effect = [
            {"config": {"id": "workflow-1", "name": "Workflow 1"}},
            {"config": {"id": "workflow-2", "name": "Workflow 2"}},
        ]

        workflows = get_workflows(db=mock_db)

        assert len(workflows) == 2
        assert workflows[0].id == "workflow-1"
        assert workflows[1].id == "workflow-2"

    def test_get_workflows_filters_by_type(self, mock_db):
        """Test get_workflows filters by WORKFLOW component type."""
        mock_db.list_components.return_value = ([], None)

        get_workflows(db=mock_db)

        mock_db.list_components.assert_called_once_with(component_type=ComponentType.WORKFLOW)

    def test_get_workflows_returns_empty_list_on_error(self, mock_db):
        """Test get_workflows returns empty list on error."""
        mock_db.list_components.side_effect = Exception("DB error")

        workflows = get_workflows(db=mock_db)

        assert workflows == []

    def test_get_workflows_skips_invalid_configs(self, mock_db):
        """Test get_workflows skips workflows with invalid configs."""
        mock_db.list_components.return_value = (
            [
                {"component_id": "valid-workflow"},
                {"component_id": "invalid-workflow"},
            ],
            None,
        )
        mock_db.get_config.side_effect = [
            {"config": {"id": "valid-workflow", "name": "Valid"}},
            {"config": None},  # Invalid config
        ]

        workflows = get_workflows(db=mock_db)

        assert len(workflows) == 1
        assert workflows[0].id == "valid-workflow"

    def test_get_workflows_sets_db_on_all_workflows(self, mock_db):
        """Test get_workflows sets db on all returned workflows via registry."""
        # The db is set via registry lookup when config contains a serialized db reference
        mock_db.id = "test-db"
        mock_db.list_components.return_value = (
            [{"component_id": "workflow-1"}],
            None,
        )
        mock_db.get_config.return_value = {
            "config": {
                "id": "workflow-1",
                "name": "Workflow 1",
                "db": {"type": "postgres", "id": "test-db"},
            }
        }

        # Create registry with the mock db registered
        registry = Registry(dbs=[mock_db])

        workflows = get_workflows(db=mock_db, registry=registry)

        assert len(workflows) == 1
        assert workflows[0].db == mock_db


# =============================================================================
# strict threading through steps
# =============================================================================


class TestWorkflowStrictThreading:
    """strict must flow from Workflow.from_dict into step-level member loads."""

    def _save_agent_with_tools(self, db):
        from agno.agent.agent import Agent
        from agno.models.openai import OpenAIChat

        def search(query: str) -> str:
            """Search for a query."""
            return f"results for {query}"

        agent = Agent(id="step-agent", name="Step Agent", model=OpenAIChat(id="gpt-4o-mini"), tools=[search])
        agent.save(db=db)
        return agent

    def test_strict_from_dict_raises_for_step_agent_with_broken_refs(self, tmp_path):
        from agno.db.sqlite import SqliteDb
        from agno.exceptions import ComponentRehydrationError

        db = SqliteDb(db_file=str(tmp_path / "wf_strict.db"))
        self._save_agent_with_tools(db)
        config = {"id": "wf1", "name": "WF", "steps": [{"type": "Step", "name": "s1", "agent_id": "step-agent"}]}

        # The step agent exists but its tools cannot be rehydrated without a registry
        with pytest.raises(ComponentRehydrationError):
            Workflow.from_dict(config, db=db, strict=True)

    def test_lenient_from_dict_degrades_step_agent_instead_of_raising(self, tmp_path):
        from agno.db.sqlite import SqliteDb

        db = SqliteDb(db_file=str(tmp_path / "wf_lenient.db"))
        self._save_agent_with_tools(db)
        config = {"id": "wf1", "name": "WF", "steps": [{"type": "Step", "name": "s1", "agent_id": "step-agent"}]}

        workflow = Workflow.from_dict(config, db=db, strict=False)

        assert workflow.steps[0].agent is not None
        assert workflow.steps[0].agent.id == "step-agent"

    def test_listing_still_shows_workflow_with_degraded_step_agent(self, tmp_path):
        from agno.db.sqlite import SqliteDb
        from agno.workflow.step import Step
        from agno.workflow.workflow import get_workflows

        db = SqliteDb(db_file=str(tmp_path / "wf_listing.db"))
        agent = self._save_agent_with_tools(db)
        workflow = Workflow(id="wf1", name="WF", steps=[Step(name="s1", agent=agent)], db=db)
        workflow.save(db=db)

        listed = get_workflows(db=db)

        assert [w.id for w in listed] == ["wf1"]


class TestStepMemberPins:
    def test_strict_load_honors_step_agent_pin_when_current_version_is_broken(self, tmp_path):
        """The workflow pinned a clean agent version at save time; a broken
        newer agent version must not make the workflow refuse."""
        from agno.agent.agent import Agent
        from agno.db.sqlite import SqliteDb
        from agno.registry import Registry
        from agno.workflow.step import Step
        from agno.workflow.workflow import get_workflow_by_id

        def broken_tool(q: str) -> str:
            """Tool."""
            return q

        db = SqliteDb(db_file=str(tmp_path / "step_pin.db"))
        member = Agent(id="sp-agent", name="SP")
        Workflow(id="sp-wf", name="WF", steps=[Step(name="s1", agent=member)]).save(db=db)
        from agno.models.openai import OpenAIChat

        member.model = OpenAIChat(id="gpt-4o-mini")
        member.tools = [broken_tool]
        member.save(db=db)

        loaded = get_workflow_by_id(db=db, id="sp-wf", registry=Registry(), strict=True)

        assert loaded is not None
        assert loaded.steps[0].agent.id == "sp-agent"

    def test_workflow_load_fetches_links_for_step_pins(self, tmp_path):
        """Workflow.load resolves step members at their pinned versions, like
        get_workflow_by_id."""
        from agno.agent.agent import Agent
        from agno.db.sqlite import SqliteDb
        from agno.workflow.step import Step

        db = SqliteDb(db_file=str(tmp_path / "load_pin.db"))
        member = Agent(id="lp-agent", name="LP", description="v1 desc")
        Workflow(id="lp-wf", name="WF", steps=[Step(name="s1", agent=member)]).save(db=db)
        member.description = "v2 desc"
        member.save(db=db)

        loaded = Workflow.load(id="lp-wf", db=db)

        assert loaded is not None
        assert loaded.steps[0].agent.description == "v1 desc"


class TestStepPinFailures:
    def test_lenient_load_degrades_deleted_step_pin_to_current_version(self, tmp_path):
        """A deleted pinned version must not make the workflow vanish from
        lenient reads; it degrades to the agent's current version with a
        warning, and strict refuses naming the pin."""
        from agno.agent.agent import Agent
        from agno.db.sqlite import SqliteDb
        from agno.exceptions import ComponentPinError
        from agno.workflow.step import Step
        from agno.workflow.workflow import get_workflow_by_id

        db = SqliteDb(db_file=str(tmp_path / "step_pin_del.db"))
        member = Agent(id="dp-agent", name="DP", description="v1")
        Workflow(id="dp-wf", name="WF", steps=[Step(name="s1", agent=member)]).save(db=db)
        member.description = "v2"
        member.save(db=db)
        links = db.get_links(component_id="dp-wf", version=1)
        pinned = next(link for link in links if link["link_kind"] == "step_agent")["child_version"]
        assert db.delete_config(component_id="dp-agent", version=pinned)

        lenient = get_workflow_by_id(db=db, id="dp-wf", strict=False)
        assert lenient is not None
        assert lenient.steps[0].agent.description == "v2"

        with pytest.raises(ComponentPinError, match=f"pins agent 'dp-agent' at version {pinned}"):
            get_workflow_by_id(db=db, id="dp-wf", strict=True)


class TestElseBranchPersistence:
    def test_save_persists_and_pins_else_branch_agents(self, tmp_path):
        """Condition else-branch agents cascade-save and pin like if-branch
        agents, so a strict reload works immediately after a save."""
        from agno.agent.agent import Agent
        from agno.db.sqlite import SqliteDb
        from agno.workflow.condition import Condition
        from agno.workflow.step import Step
        from agno.workflow.workflow import get_workflow_by_id

        db = SqliteDb(db_file=str(tmp_path / "else_save.db"))
        if_agent = Agent(id="if-agent", name="If")
        else_agent = Agent(id="else-agent", name="Else", description="v1")
        workflow = Workflow(
            id="else-wf",
            name="WF",
            steps=[
                Condition(
                    name="branch",
                    evaluator=True,
                    steps=[Step(name="if-step", agent=if_agent)],
                    else_steps=[Step(name="else-step", agent=else_agent)],
                )
            ],
        )
        workflow.save(db=db)

        links = db.get_links(component_id="else-wf", version=1)
        pinned_children = {link["child_component_id"]: link["child_version"] for link in links}
        assert "else-agent" in pinned_children

        # A later publish of the else agent must not change the pinned load
        else_agent.description = "v2"
        else_agent.save(db=db)

        loaded = get_workflow_by_id(db=db, id="else-wf", strict=True)
        assert loaded is not None
        else_step = loaded.steps[0].else_steps[0]
        assert else_step.agent.description == "v1"


class TestWritePathFidelity:
    def test_unnamed_degraded_step_round_trips_without_a_placeholder_name(self, tmp_path):
        """A nameless step whose reference degrades must stay nameless: the
        placeholder must never become the step's stored display name."""
        from agno.agent.agent import Agent
        from agno.db.sqlite import SqliteDb
        from agno.workflow.step import Step

        db = SqliteDb(db_file=str(tmp_path / "noname.db"))
        Workflow(id="nn-wf", name="WF", steps=[Step(agent=Agent(id="nn-agent", name="A"))]).save(db=db)
        db.delete_component("nn-agent", hard_delete=True)

        loaded = Workflow.load(id="nn-wf", db=db, strict=False)

        assert loaded is not None
        assert loaded.steps[0].name is None
        assert loaded.steps[0].to_dict().get("agent_id") == "nn-agent"

    def test_deep_copy_preserves_container_review_config(self):
        """deep_copy must not reset container HITL/error config: the per-request
        AgentOS path deep-copies every workflow before it runs."""
        from agno.workflow.condition import Condition
        from agno.workflow.loop import Loop
        from agno.workflow.step import Step, StepInput, StepOutput
        from agno.workflow.types import HumanReview

        def go(step_input: StepInput) -> StepOutput:
            return StepOutput(content="x")

        workflow = Workflow(
            id="hr-wf",
            name="WF",
            steps=[
                Condition(
                    name="c",
                    evaluator=True,
                    steps=[Step(name="s", executor=go)],
                    human_review=HumanReview(requires_confirmation=True, on_error="cancel", max_retries=9),
                ),
                Loop(name="l", steps=[Step(name="s2", executor=go)], forward_iteration_output=True),
            ],
        )

        copied = workflow.deep_copy()

        assert copied.steps[0].human_review.on_error == workflow.steps[0].human_review.on_error
        assert copied.steps[0].human_review.max_retries == 9
        assert copied.steps[1].forward_iteration_output is True

    def test_save_persists_a_nested_workflow_step_and_pins_it(self, tmp_path):
        from agno.db.sqlite import SqliteDb
        from agno.workflow.step import Step, StepInput, StepOutput

        def leaf(step_input: StepInput) -> StepOutput:
            return StepOutput(content="x")

        db = SqliteDb(db_file=str(tmp_path / "nested_save.db"))
        sub = Workflow(id="sub-wf", name="Sub", steps=[Step(name="x", executor=leaf)])
        parent = Workflow(id="parent-wf", name="Parent", steps=[Step(name="n", workflow=sub)])

        version = parent.save(db=db)

        assert version == 1
        links = db.get_links(component_id="parent-wf", version=1)
        nested = [link for link in links if link["child_component_id"] == "sub-wf"]
        assert nested and nested[0]["child_version"] is not None


def _honesty_enrich(step_input):
    from agno.workflow.step import StepOutput

    return StepOutput(content="x")


def _honesty_cases():
    from agno.workflow.condition import Condition
    from agno.workflow.parallel import Parallel
    from agno.workflow.step import Step
    from agno.workflow.steps import Steps

    return {
        "plain": lambda: [Step(name="s1", executor=_honesty_enrich)],
        "skip_on_failure": lambda: [Step(name="s1", executor=_honesty_enrich, skip_on_failure=True)],
        "condition_on_error_skip": lambda: [
            Condition(name="c", evaluator=True, steps=[Step(name="s1", executor=_honesty_enrich)], on_error="skip")
        ],
        "steps_container": lambda: [Steps(name="grp", steps=[Step(name="s1", executor=_honesty_enrich)])],
        "parallel_container": lambda: [Parallel(Step(name="s1", executor=_honesty_enrich), name="par")],
    }


class TestLenientRunHonesty:
    """A run over an unresolved placeholder must refuse on every entry path
    and through every tolerance knob; skipping a step that could not do its
    work is not error tolerance."""

    def _load_broken(self, tmp_path, tag):
        from agno.db.sqlite import SqliteDb
        from agno.registry import Registry

        db = SqliteDb(db_file=str(tmp_path / f"{tag}.db"))
        Workflow(id=f"{tag}-wf", name="WF", steps=_honesty_cases()[tag]()).save(db=db)
        loaded = Workflow.load(id=f"{tag}-wf", db=db, registry=Registry())
        assert loaded is not None
        return loaded

    @pytest.mark.parametrize("tag", list(_honesty_cases().keys()))
    def test_sync_run_refuses(self, tmp_path, tag):
        from agno.workflow.step import UnresolvableCallableError

        loaded = self._load_broken(tmp_path, tag)
        with pytest.raises(UnresolvableCallableError):
            loaded.run(input="go")

    @pytest.mark.parametrize("tag", list(_honesty_cases().keys()))
    def test_sync_stream_refuses(self, tmp_path, tag):
        from agno.workflow.step import UnresolvableCallableError

        loaded = self._load_broken(tmp_path, tag)
        with pytest.raises(UnresolvableCallableError):
            for _ in loaded.run(input="go", stream=True):
                pass

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tag", list(_honesty_cases().keys()))
    async def test_async_run_refuses(self, tmp_path, tag):
        from agno.workflow.step import UnresolvableCallableError

        loaded = self._load_broken(tmp_path, tag)
        with pytest.raises(UnresolvableCallableError):
            await loaded.arun(input="go")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tag", list(_honesty_cases().keys()))
    async def test_async_stream_refuses(self, tmp_path, tag):
        from agno.workflow.step import UnresolvableCallableError

        loaded = self._load_broken(tmp_path, tag)
        with pytest.raises(UnresolvableCallableError):
            async for _ in loaded.arun(input="go", stream=True):
                pass


class TestSaveCollisions:
    def test_save_fails_loudly_when_two_pins_collide_on_one_key(self, tmp_path):
        from agno.agent.agent import Agent
        from agno.db.sqlite import SqliteDb
        from agno.workflow.loop import Loop
        from agno.workflow.step import Step

        db = SqliteDb(db_file=str(tmp_path / "collide.db"))
        # Auto-generated step_ids keep link keys unique; an explicit shared
        # step_id is the collision the save must refuse to half-persist.
        workflow = Workflow(
            id="col-wf",
            name="WF",
            steps=[
                Loop(name="l1", steps=[Step(step_id="dup", name="dup", agent=Agent(id="col-a", name="A"))]),
                Loop(name="l2", steps=[Step(step_id="dup", name="dup", agent=Agent(id="col-b", name="B"))]),
            ],
        )

        with pytest.raises(ValueError, match="give steps distinct names"):
            workflow.save(db=db)

        # The parent snapshot was refused whole: no config version exists.
        assert db.get_config(component_id="col-wf") is None

    def test_else_branch_pin_resolves_to_its_own_version(self, tmp_path):
        """The same child id pinned differently in the if and else branches
        must reload each branch at its own pin."""
        from agno.agent.agent import Agent
        from agno.db.sqlite import SqliteDb
        from agno.workflow.condition import Condition
        from agno.workflow.step import Step
        from agno.workflow.workflow import get_workflow_by_id

        db = SqliteDb(db_file=str(tmp_path / "else_pin.db"))
        if_agent = Agent(id="eb-agent", name="A", description="if-version")
        else_agent = Agent(id="eb-agent", name="A", description="else-version")
        Workflow(
            id="eb-wf",
            name="WF",
            steps=[
                Condition(
                    name="branch",
                    evaluator=True,
                    # Explicit ordered step_ids: with the '#else' lookup broken
                    # the fallback returns the FIRST link (the if pin), so this
                    # test fails on a revert instead of passing by row order.
                    steps=[Step(step_id="aaa-if", name="if-step", agent=if_agent)],
                    else_steps=[Step(step_id="bbb-else", name="else-step", agent=else_agent)],
                )
            ],
        ).save(db=db)

        loaded = get_workflow_by_id(db=db, id="eb-wf", strict=True)

        assert loaded is not None
        condition = loaded.steps[0]
        assert condition.steps[0].agent.description == "if-version"
        assert condition.else_steps[0].agent.description == "else-version"


class TestNestedElsePins:
    def test_doubly_nested_else_branch_resolves_its_own_pin(self, tmp_path):
        """Nested else branches accumulate '#else' per level; the lookup must
        match the whole chain so each branch reloads its own pinned version."""
        from agno.agent.agent import Agent
        from agno.db.sqlite import SqliteDb
        from agno.workflow.condition import Condition
        from agno.workflow.step import Step
        from agno.workflow.workflow import get_workflow_by_id

        db = SqliteDb(db_file=str(tmp_path / "nested_else.db"))
        outer_if = Agent(id="ne-agent", name="A", description="outer-if")
        inner_else = Agent(id="ne-agent", name="A", description="inner-else")
        Workflow(
            id="ne-wf",
            name="WF",
            steps=[
                Condition(
                    name="outer",
                    evaluator=True,
                    steps=[Step(step_id="aaa-oif", name="oif", agent=outer_if)],
                    else_steps=[
                        Condition(
                            name="inner",
                            evaluator=True,
                            steps=[],
                            else_steps=[Step(step_id="bbb-iel", name="iel", agent=inner_else)],
                        )
                    ],
                )
            ],
        ).save(db=db)

        links = {link["link_key"]: link["child_version"] for link in db.get_links(component_id="ne-wf", version=1)}
        assert "bbb-iel#else#else" in links

        loaded = get_workflow_by_id(db=db, id="ne-wf", strict=True)
        assert loaded is not None
        inner_condition = loaded.steps[0].else_steps[0]
        assert inner_condition.else_steps[0].agent.description == "inner-else"
        assert loaded.steps[0].steps[0].agent.description == "outer-if"


class TestBranchQualifiedPins:
    def test_duplicate_step_ids_across_branches_resolve_their_own_pins(self, tmp_path):
        """Explicit duplicate step_ids in the if and else branches must each
        reload their own pinned version via the branch-qualified key."""
        from agno.agent.agent import Agent
        from agno.db.sqlite import SqliteDb
        from agno.workflow.condition import Condition
        from agno.workflow.step import Step
        from agno.workflow.workflow import get_workflow_by_id

        db = SqliteDb(db_file=str(tmp_path / "dup_branch.db"))
        if_agent = Agent(id="db-agent", name="A", description="if-v")
        else_agent = Agent(id="db-agent", name="A", description="else-v")
        Workflow(
            id="db-wf",
            name="WF",
            steps=[
                Condition(
                    name="branch",
                    evaluator=True,
                    steps=[Step(step_id="dup", name="dup", agent=if_agent)],
                    else_steps=[Step(step_id="dup", name="dup", agent=else_agent)],
                )
            ],
        ).save(db=db)

        loaded = get_workflow_by_id(db=db, id="db-wf", strict=True)

        assert loaded is not None
        condition = loaded.steps[0]
        assert condition.steps[0].agent.description == "if-v"
        assert condition.else_steps[0].agent.description == "else-v"

    def test_lookalike_link_key_never_satisfies_another_step(self, tmp_path):
        """A step_id like 'x#else-other' is its own exact key; it must not be
        claimed by step 'x' via prefix matching."""
        from agno.agent.agent import Agent
        from agno.db.sqlite import SqliteDb
        from agno.workflow.step import Step
        from agno.workflow.workflow import get_workflow_by_id

        db = SqliteDb(db_file=str(tmp_path / "lookalike.db"))
        first = Agent(id="la-agent", name="A", description="x-v")
        second = Agent(id="la-agent", name="A", description="other-v")
        Workflow(
            id="la-wf",
            name="WF",
            steps=[
                Step(step_id="x", name="x", agent=first),
                Step(step_id="x#else-other", name="other", agent=second),
            ],
        ).save(db=db)

        loaded = get_workflow_by_id(db=db, id="la-wf", strict=True)

        assert loaded is not None
        assert loaded.steps[0].agent.description == "x-v"
        assert loaded.steps[1].agent.description == "other-v"

    def test_strict_refuses_ambiguous_legacy_pins(self, tmp_path):
        """With no exact key match and multiple disagreeing pins for a child,
        strict refuses instead of silently picking the first link."""
        from agno.agent.agent import Agent
        from agno.db.base import ComponentType
        from agno.db.sqlite import SqliteDb
        from agno.exceptions import ComponentRehydrationError
        from agno.workflow.workflow import get_workflow_by_id

        db = SqliteDb(db_file=str(tmp_path / "legacy_amb.db"))
        agent = Agent(id="am-agent", name="A", description="v1")
        agent.save(db=db)
        agent.description = "v2"
        agent.save(db=db)
        db.upsert_component(component_id="am-wf", component_type=ComponentType.WORKFLOW, name="WF")
        db.upsert_config(
            component_id="am-wf",
            config={
                "id": "am-wf",
                "name": "WF",
                "steps": [{"type": "Step", "step_id": "renamed", "name": "renamed", "agent_id": "am-agent"}],
            },
            links=[
                {
                    "link_kind": "step_agent",
                    "link_key": "old-key-1",
                    "child_component_id": "am-agent",
                    "child_version": 1,
                    "position": 0,
                },
                {
                    "link_kind": "step_agent",
                    "link_key": "old-key-2",
                    "child_component_id": "am-agent",
                    "child_version": 2,
                    "position": 1,
                },
            ],
            stage="published",
        )

        with pytest.raises(ComponentRehydrationError, match="multiple versions"):
            get_workflow_by_id(db=db, id="am-wf", strict=True)
