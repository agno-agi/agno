"""
Unit tests for Team configuration serialization and persistence.

Tests cover:
- to_dict(): Serialization of team to dictionary
- from_dict(): Deserialization of team from dictionary
- save(): Saving team to database (including members)
- load(): Loading team from database (with hydrated members)
- delete(): Deleting team from database
- get_team_by_id(): Helper function to get team by ID
- get_teams(): Helper function to get all teams
"""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from agno.agent.agent import Agent
from agno.db.base import BaseDb, ComponentType
from agno.registry import Registry
from agno.session import TeamSession
from agno.team.team import Team, get_team_by_id, get_teams

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
    db.upsert_component_link = MagicMock()
    db.load_component_graph = MagicMock()
    db.to_dict = MagicMock(return_value={"type": "postgres", "id": "test-db"})

    return db


@pytest.fixture
def basic_team():
    """Create a basic team for testing."""
    return Team(
        id="test-team",
        name="Test Team",
        description="A test team for unit testing",
        members=[],
    )


@pytest.fixture
def member_agent():
    """Create a member agent for team testing."""
    return Agent(
        id="member-agent",
        name="Member Agent",
        role="A member agent",
    )


@pytest.fixture
def team_with_members(member_agent):
    """Create a team with member agents."""
    agent2 = Agent(
        id="agent-2",
        name="Agent 2",
        role="Second agent",
    )
    return Team(
        id="team-with-members",
        name="Team With Members",
        members=[member_agent, agent2],
    )


@pytest.fixture
def team_with_model():
    """Create a team with a real model."""
    from agno.models.openai import OpenAIChat

    model = OpenAIChat(id="gpt-4o-mini")
    return Team(
        id="model-team",
        name="Model Team",
        model=model,
        members=[],
    )


@pytest.fixture
def team_with_settings():
    """Create a team with various settings configured."""
    return Team(
        id="settings-team",
        name="Settings Team",
        description="Team with many settings",
        instructions="Work together efficiently",
        markdown=True,
        debug_mode=True,
        retries=3,
        respond_directly=True,
        delegate_to_all_members=True,
        add_datetime_to_context=True,
        members=[],
    )


@pytest.fixture
def sample_team_config() -> Dict[str, Any]:
    """Sample team configuration dictionary."""
    return {
        "id": "sample-team",
        "name": "Sample Team",
        "description": "A sample team",
        "instructions": "Be helpful",
        "markdown": True,
    }


# =============================================================================
# to_dict() Tests
# =============================================================================


class TestTeamToDict:
    """Tests for Team.to_dict() method."""

    def test_to_dict_basic_team(self, basic_team):
        """Test to_dict with a basic team."""
        config = basic_team.to_dict()

        assert config["id"] == "test-team"
        assert config["name"] == "Test Team"
        assert config["description"] == "A test team for unit testing"

    def test_to_dict_with_model(self, team_with_model):
        """Test to_dict includes model configuration."""
        config = team_with_model.to_dict()

        assert "model" in config
        assert config["model"]["provider"] == "OpenAI"
        assert config["model"]["id"] == "gpt-4o-mini"

    def test_to_dict_with_members(self, team_with_members):
        """Test to_dict serializes members as references."""
        config = team_with_members.to_dict()

        assert "members" in config
        assert len(config["members"]) == 2
        assert config["members"][0] == {"type": "agent", "agent_id": "member-agent"}
        assert config["members"][1] == {"type": "agent", "agent_id": "agent-2"}

    def test_to_dict_with_settings(self, team_with_settings):
        """Test to_dict preserves all settings."""
        config = team_with_settings.to_dict()

        assert config["id"] == "settings-team"
        assert config["name"] == "Settings Team"
        assert config["description"] == "Team with many settings"
        assert config["instructions"] == "Work together efficiently"
        assert config["markdown"] is True
        assert config["debug_mode"] is True
        assert config["retries"] == 3
        assert config["respond_directly"] is True
        assert config["delegate_to_all_members"] is True
        assert config["add_datetime_to_context"] is True

    def test_to_dict_excludes_default_values(self):
        """Test that default values are not included in the config."""
        team = Team(id="minimal-team", members=[])
        config = team.to_dict()

        # Default values should not be present
        assert "markdown" not in config  # defaults to False
        assert "debug_mode" not in config  # defaults to False
        assert "retries" not in config  # defaults to 0
        assert "respond_directly" not in config  # defaults to False

    def test_store_history_messages_default_is_false(self):
        """Test store_history_messages defaults to False and is omitted from config."""
        team = Team(id="history-default-team", members=[])

        assert team.store_history_messages is False
        assert "store_history_messages" not in team.to_dict()

    def test_add_search_knowledge_instructions_default_omitted(self):
        """Test add_search_knowledge_instructions default is omitted from config."""
        team = Team(id="search-default-team", members=[])

        assert "add_search_knowledge_instructions" not in team.to_dict()

    def test_add_search_knowledge_instructions_false_is_serialized(self):
        """Test add_search_knowledge_instructions=False is serialized in config."""
        team = Team(id="search-false-team", members=[], add_search_knowledge_instructions=False)
        config = team.to_dict()

        assert config["add_search_knowledge_instructions"] is False

    def test_to_dict_with_db(self, basic_team, mock_db):
        """Test to_dict includes database configuration."""
        basic_team.db = mock_db
        config = basic_team.to_dict()

        assert "db" in config
        assert config["db"] == {"type": "postgres", "id": "test-db"}

    def test_to_dict_with_instructions_list(self):
        """Test to_dict handles instructions as a list."""
        team = Team(
            id="list-instructions-team",
            instructions=["Step 1: Coordinate", "Step 2: Execute"],
            members=[],
        )
        config = team.to_dict()

        assert config["instructions"] == ["Step 1: Coordinate", "Step 2: Execute"]

    def test_to_dict_with_system_message(self):
        """Test to_dict includes system message when it's a string."""
        team = Team(
            id="system-message-team",
            system_message="You are a coordinating team leader.",
            members=[],
        )
        config = team.to_dict()

        assert config["system_message"] == "You are a coordinating team leader."

    def test_to_dict_with_metadata(self):
        """Test to_dict includes metadata."""
        team = Team(
            id="metadata-team",
            metadata={"version": "1.0", "team_type": "research"},
            members=[],
        )
        config = team.to_dict()

        assert config["metadata"] == {"version": "1.0", "team_type": "research"}

    def test_to_dict_with_nested_team(self):
        """Test to_dict serializes nested team as reference."""
        inner_team = Team(id="inner-team", name="Inner Team", members=[])
        outer_team = Team(
            id="outer-team",
            name="Outer Team",
            members=[inner_team],
        )
        config = outer_team.to_dict()

        assert "members" in config
        assert len(config["members"]) == 1
        assert config["members"][0] == {"type": "team", "team_id": "inner-team"}

    def test_to_dict_with_mode(self):
        """Test to_dict includes mode and max_iterations."""
        from agno.team.mode import TeamMode

        team = Team(id="task-team", members=[], mode=TeamMode.tasks, max_iterations=20)
        config = team.to_dict()

        assert config["mode"] == "tasks"
        assert config["max_iterations"] == 20

    def test_to_dict_mode_default_not_serialized(self):
        """Test that default max_iterations is not serialized."""
        from agno.team.mode import TeamMode

        team = Team(id="coord-team", members=[], mode=TeamMode.coordinate)
        config = team.to_dict()

        assert config["mode"] == "coordinate"
        assert "max_iterations" not in config  # default=10 should not be serialized


# =============================================================================
# from_dict() Tests
# =============================================================================


class TestTeamFromDict:
    """Tests for Team.from_dict() method."""

    def test_from_dict_basic(self, sample_team_config):
        """Test from_dict creates team with basic config."""
        team = Team.from_dict(sample_team_config)

        assert team.id == "sample-team"
        assert team.name == "Sample Team"
        assert team.description == "A sample team"
        assert team.instructions == "Be helpful"
        assert team.markdown is True

    def test_from_dict_with_model(self):
        """Test from_dict reconstructs model from config."""
        from agno.models.openai import OpenAIChat

        config = {
            "id": "model-team",
            "name": "Model Team",
            "model": {"provider": "openai", "id": "gpt-4o-mini"},
        }

        team = Team.from_dict(config)

        assert team.model is not None
        assert isinstance(team.model, OpenAIChat)
        assert team.model.id == "gpt-4o-mini"

    def test_from_dict_preserves_settings(self):
        """Test from_dict preserves all settings."""
        config = {
            "id": "full-team",
            "name": "Full Team",
            "debug_mode": True,
            "retries": 3,
            "respond_directly": True,
            "delegate_to_all_members": True,
            "add_datetime_to_context": True,
        }

        team = Team.from_dict(config)

        assert team.debug_mode is True
        assert team.retries == 3
        assert team.respond_directly is True
        assert team.delegate_to_all_members is True
        assert team.add_datetime_to_context is True

    def test_from_dict_with_db_postgres(self):
        """Test from_dict reconstructs PostgresDb."""
        config = {
            "id": "db-team",
            "db": {"type": "postgres", "db_url": "postgresql://localhost/test"},
        }

        with patch("agno.db.postgres.PostgresDb.from_dict") as mock_from_dict:
            mock_db = MagicMock()
            mock_from_dict.return_value = mock_db

            team = Team.from_dict(config)

            mock_from_dict.assert_called_once()
            assert team.db == mock_db

    def test_from_dict_with_db_sqlite(self):
        """Test from_dict reconstructs SqliteDb."""
        config = {
            "id": "sqlite-team",
            "db": {"type": "sqlite", "db_file": "/tmp/test.db"},
        }

        with patch("agno.db.sqlite.SqliteDb.from_dict") as mock_from_dict:
            mock_db = MagicMock()
            mock_from_dict.return_value = mock_db

            team = Team.from_dict(config)

            mock_from_dict.assert_called_once()
            assert team.db == mock_db

    def test_from_dict_with_registry_tools(self):
        """Test from_dict uses registry to rehydrate tools."""
        config = {
            "id": "tools-team",
            "tools": [{"name": "search", "description": "Search the web"}],
        }

        mock_registry = MagicMock()
        mock_tool = MagicMock()
        mock_registry.rehydrate_function.return_value = mock_tool

        team = Team.from_dict(config, registry=mock_registry)

        mock_registry.rehydrate_function.assert_called_once()
        assert team.tools == [mock_tool]

    def test_from_dict_without_registry_removes_tools(self):
        """Test from_dict removes tools when no registry is provided."""
        config = {
            "id": "no-registry-team",
            "tools": [{"name": "search"}],
        }

        team = Team.from_dict(config)

        # Tools should be None/empty since no registry was provided
        assert team.tools is None or team.tools == []

    def test_from_dict_with_members_loads_from_db(self, mock_db):
        """Test from_dict loads member agents from database."""
        config = {
            "id": "members-team",
            "members": [{"type": "agent", "agent_id": "agent-1"}],
        }

        # get_agent_by_id is imported inside from_dict from agno.agent
        with patch("agno.agent.get_agent_by_id") as mock_get_agent:
            mock_agent = MagicMock()
            mock_get_agent.return_value = mock_agent

            team = Team.from_dict(config, db=mock_db)

            mock_get_agent.assert_called_once_with(id="agent-1", db=mock_db, registry=None)
            assert team.members == [mock_agent]

    def test_from_dict_roundtrip(self, team_with_settings):
        """Test that to_dict -> from_dict preserves team configuration."""
        config = team_with_settings.to_dict()
        reconstructed = Team.from_dict(config)

        assert reconstructed.id == team_with_settings.id
        assert reconstructed.name == team_with_settings.name
        assert reconstructed.description == team_with_settings.description
        assert reconstructed.markdown == team_with_settings.markdown
        assert reconstructed.debug_mode == team_with_settings.debug_mode
        assert reconstructed.retries == team_with_settings.retries

    def test_from_dict_with_mode(self):
        """Test from_dict reconstructs mode and max_iterations."""
        from agno.team.mode import TeamMode

        config = {
            "id": "task-team",
            "mode": "tasks",
            "max_iterations": 25,
        }
        team = Team.from_dict(config)

        assert team.mode == TeamMode.tasks
        assert team.max_iterations == 25

    def test_from_dict_mode_roundtrip(self):
        """Test to_dict -> from_dict roundtrip preserves mode."""
        from agno.team.mode import TeamMode

        team = Team(id="rt-team", members=[], mode=TeamMode.route, max_iterations=15)
        config = team.to_dict()
        reconstructed = Team.from_dict(config)

        assert reconstructed.mode == TeamMode.route
        assert reconstructed.max_iterations == 15

    def test_from_dict_no_mode_defaults(self):
        """Test from_dict with no mode field defaults correctly."""
        config = {"id": "no-mode-team"}
        team = Team.from_dict(config)

        # Mode should be inferred as coordinate (default)
        from agno.team.mode import TeamMode

        assert team.mode == TeamMode.coordinate
        assert team.max_iterations == 10


# =============================================================================
# save() Tests
# =============================================================================


class TestTeamSave:
    """Tests for Team.save() method."""

    def test_save_calls_upsert_component(self, basic_team, mock_db):
        """Test save calls upsert_component with correct parameters."""
        mock_db.upsert_config.return_value = {"version": 1}

        basic_team.db = mock_db
        version = basic_team.save()

        mock_db.upsert_component.assert_called_once_with(
            component_id="test-team",
            component_type=ComponentType.TEAM,
            name="Test Team",
            description="A test team for unit testing",
            metadata=None,
        )
        assert version == 1

    def test_save_calls_upsert_config(self, basic_team, mock_db):
        """Test save calls upsert_config with team config."""
        mock_db.upsert_config.return_value = {"version": 2}

        basic_team.db = mock_db
        version = basic_team.save()

        mock_db.upsert_config.assert_called_once()
        call_args = mock_db.upsert_config.call_args
        assert call_args.kwargs["component_id"] == "test-team"
        assert "config" in call_args.kwargs
        assert version == 2

    def test_save_with_members_saves_each_member(self, mock_db, member_agent):
        """Test save saves each member agent."""
        mock_db.upsert_config.return_value = {"version": 1}

        # Create a spy on member.save
        member_agent.save = MagicMock(return_value=1)

        team = Team(
            id="team-with-member",
            name="Team",
            members=[member_agent],
            db=mock_db,
        )
        team.save()

        # Member should be saved
        member_agent.save.assert_called_once()

    def test_save_creates_member_links(self, mock_db, member_agent):
        """Test save creates links for members."""
        mock_db.upsert_config.return_value = {"version": 1}
        member_agent.save = MagicMock(return_value=5)

        team = Team(
            id="linked-team",
            name="Linked Team",
            members=[member_agent],
            db=mock_db,
        )
        team.save()

        # Check that links were passed to upsert_config
        call_args = mock_db.upsert_config.call_args
        links = call_args.kwargs.get("links")
        assert links is not None
        assert len(links) == 1
        assert links[0]["link_kind"] == "member"
        assert links[0]["child_component_id"] == "member-agent"
        assert links[0]["child_version"] == 5
        assert links[0]["meta"]["type"] == "agent"

    def test_save_with_explicit_db(self, basic_team, mock_db):
        """Test save uses explicitly provided db."""
        mock_db.upsert_config.return_value = {"version": 1}

        version = basic_team.save(db=mock_db)

        mock_db.upsert_component.assert_called_once()
        mock_db.upsert_config.assert_called_once()
        assert version == 1

    def test_save_with_label(self, basic_team, mock_db):
        """Test save passes label to upsert_config."""
        mock_db.upsert_config.return_value = {"version": 1}

        basic_team.db = mock_db
        basic_team.save(label="production")

        call_args = mock_db.upsert_config.call_args
        assert call_args.kwargs["label"] == "production"

    def test_save_with_stage(self, basic_team, mock_db):
        """Test save passes stage to upsert_config."""
        mock_db.upsert_config.return_value = {"version": 1}

        basic_team.db = mock_db
        basic_team.save(stage="draft")

        call_args = mock_db.upsert_config.call_args
        assert call_args.kwargs["stage"] == "draft"

    def test_save_without_db_raises_error(self, basic_team):
        """Test save raises error when no db is available."""
        with pytest.raises(ValueError, match="Db not initialized or provided"):
            basic_team.save()

    def test_save_handles_db_error(self, basic_team, mock_db):
        """Test save raises error when database operation fails."""
        mock_db.upsert_component.side_effect = Exception("Database error")

        basic_team.db = mock_db

        with pytest.raises(Exception, match="Database error"):
            basic_team.save()


# =============================================================================
# load() Tests
# =============================================================================


class TestTeamLoad:
    """Tests for Team.load() class method."""

    def test_load_returns_team(self, mock_db, sample_team_config):
        """Test load returns a team from database."""
        mock_db.load_component_graph.return_value = {
            "component": {"component_id": "sample-team"},
            "config": {"config": sample_team_config},
            "children": [],
        }

        team = Team.load(id="sample-team", db=mock_db)

        assert team is not None
        assert team.id == "sample-team"
        assert team.name == "Sample Team"

    def test_load_with_version(self, mock_db):
        """Test load retrieves specific version."""
        mock_db.load_component_graph.return_value = {
            "component": {"component_id": "versioned-team"},
            "config": {"config": {"id": "versioned-team", "name": "V2 Team"}},
            "children": [],
        }

        Team.load(id="versioned-team", db=mock_db, version=2)

        mock_db.load_component_graph.assert_called_once_with("versioned-team", version=2, label=None)

    def test_load_with_label(self, mock_db):
        """Test load retrieves labeled version."""
        mock_db.load_component_graph.return_value = {
            "component": {"component_id": "labeled-team"},
            "config": {"config": {"id": "labeled-team", "name": "Production Team"}},
            "children": [],
        }

        Team.load(id="labeled-team", db=mock_db, label="production")

        mock_db.load_component_graph.assert_called_once_with("labeled-team", version=None, label="production")

    def test_load_hydrates_member_agents(self, mock_db):
        """Test load hydrates member agents from graph."""
        mock_db.load_component_graph.return_value = {
            "component": {"component_id": "team-with-members"},
            "config": {"config": {"id": "team-with-members", "name": "Team"}},
            "children": [
                {
                    "link": {"meta": {"type": "agent"}},
                    "graph": {
                        "component": {"component_id": "agent-1"},
                        "config": {"config": {"id": "agent-1", "name": "Agent 1"}},
                    },
                }
            ],
        }

        team = Team.load(id="team-with-members", db=mock_db)

        assert team is not None
        assert len(team.members) == 1
        assert team.members[0].id == "agent-1"

    def test_load_returns_none_when_not_found(self, mock_db):
        """Test load returns None when team not found."""
        mock_db.load_component_graph.return_value = None

        team = Team.load(id="nonexistent-team", db=mock_db)

        assert team is None

    def test_load_returns_none_when_config_missing(self, mock_db):
        """Test load returns None when config is missing."""
        mock_db.load_component_graph.return_value = {
            "component": {"component_id": "empty-config"},
            "config": {"config": None},
            "children": [],
        }

        team = Team.load(id="empty-config-team", db=mock_db)

        assert team is None

    def test_load_sets_db_on_team(self, mock_db):
        """Test load sets db attribute on returned team."""
        mock_db.load_component_graph.return_value = {
            "component": {"component_id": "db-team"},
            "config": {"config": {"id": "db-team", "name": "DB Team"}},
            "children": [],
        }

        team = Team.load(id="db-team", db=mock_db)

        assert team is not None
        assert team.db == mock_db


# =============================================================================
# delete() Tests
# =============================================================================


class TestTeamDelete:
    """Tests for Team.delete() method."""

    def test_delete_calls_delete_component(self, basic_team, mock_db):
        """Test delete calls delete_component."""
        mock_db.delete_component.return_value = True

        basic_team.db = mock_db
        result = basic_team.delete()

        mock_db.delete_component.assert_called_once_with(component_id="test-team", hard_delete=False)
        assert result is True

    def test_delete_with_hard_delete(self, basic_team, mock_db):
        """Test delete with hard_delete flag."""
        mock_db.delete_component.return_value = True

        basic_team.db = mock_db
        result = basic_team.delete(hard_delete=True)

        mock_db.delete_component.assert_called_once_with(component_id="test-team", hard_delete=True)
        assert result is True

    def test_delete_with_explicit_db(self, basic_team, mock_db):
        """Test delete uses explicitly provided db."""
        mock_db.delete_component.return_value = True

        result = basic_team.delete(db=mock_db)

        mock_db.delete_component.assert_called_once()
        assert result is True

    def test_delete_without_db_raises_error(self, basic_team):
        """Test delete raises error when no db is available."""
        with pytest.raises(ValueError, match="Db not initialized or provided"):
            basic_team.delete()

    def test_delete_returns_false_on_failure(self, basic_team, mock_db):
        """Test delete returns False when operation fails."""
        mock_db.delete_component.return_value = False

        basic_team.db = mock_db
        result = basic_team.delete()

        assert result is False


class TestTeamSessionNaming:
    def test_generate_session_name_fallback_after_max_retries(self):
        """Test generate_session_name falls back after repeated invalid model output."""
        team = Team(id="session-name-team", members=[])
        team.model = MagicMock()
        team.model.response = MagicMock(return_value=MagicMock(content=None))

        session = TeamSession(session_id="session-1", runs=[])
        session_name = team.generate_session_name(session=session)

        assert session_name == "Team Session"
        assert team.model.response.call_count == 4


# =============================================================================
# get_team_by_id() Tests
# =============================================================================


class TestGetTeamById:
    """Tests for get_team_by_id() helper function."""

    def test_get_team_by_id_returns_team(self, mock_db):
        """Test get_team_by_id returns team from database."""
        mock_db.get_config.return_value = {"config": {"id": "found-team", "name": "Found Team"}}

        team = get_team_by_id(db=mock_db, id="found-team")

        assert team is not None
        assert team.id == "found-team"
        assert team.name == "Found Team"

    def test_get_team_by_id_with_version(self, mock_db):
        """Test get_team_by_id retrieves specific version."""
        mock_db.get_config.return_value = {"config": {"id": "versioned", "name": "V3"}}

        get_team_by_id(db=mock_db, id="versioned", version=3)

        mock_db.get_config.assert_called_once_with(component_id="versioned", version=3, label=None)

    def test_get_team_by_id_with_label(self, mock_db):
        """Test get_team_by_id retrieves labeled version."""
        mock_db.get_config.return_value = {"config": {"id": "labeled", "name": "Staging"}}

        get_team_by_id(db=mock_db, id="labeled", label="staging")

        mock_db.get_config.assert_called_once_with(component_id="labeled", version=None, label="staging")

    def test_get_team_by_id_with_registry(self, mock_db):
        """Test get_team_by_id passes registry."""
        mock_db.get_config.return_value = {"config": {"id": "registry-team", "tools": [{"name": "calc"}]}}

        mock_registry = MagicMock()
        mock_registry.rehydrate_function.return_value = MagicMock()

        team = get_team_by_id(db=mock_db, id="registry-team", registry=mock_registry)

        assert team is not None

    def test_get_team_by_id_returns_none_when_not_found(self, mock_db):
        """Test get_team_by_id returns None when not found."""
        mock_db.get_config.return_value = None

        team = get_team_by_id(db=mock_db, id="missing")

        assert team is None

    def test_get_team_by_id_sets_db(self, mock_db):
        """Test get_team_by_id sets db on returned team via registry."""
        # The db is set via registry lookup when config contains a serialized db reference
        mock_db.id = "test-db"
        mock_db.get_config.return_value = {
            "config": {
                "id": "db-team",
                "name": "DB Team",
                "db": {"type": "postgres", "id": "test-db"},
            }
        }

        # Create registry with the mock db registered
        registry = Registry(dbs=[mock_db])

        team = get_team_by_id(db=mock_db, id="db-team", registry=registry)

        assert team is not None
        assert team.db == mock_db

    def test_get_team_by_id_handles_error(self, mock_db):
        """Test get_team_by_id returns None on error."""
        mock_db.get_config.side_effect = Exception("DB error")

        team = get_team_by_id(db=mock_db, id="error-team")

        assert team is None


# =============================================================================
# get_teams() Tests
# =============================================================================


class TestGetTeams:
    """Tests for get_teams() helper function."""

    def test_get_teams_returns_list(self, mock_db):
        """Test get_teams returns list of teams."""
        mock_db.list_components.return_value = (
            [
                {"component_id": "team-1"},
                {"component_id": "team-2"},
            ],
            None,
        )
        mock_db.get_config.side_effect = [
            {"config": {"id": "team-1", "name": "Team 1"}},
            {"config": {"id": "team-2", "name": "Team 2"}},
        ]

        teams = get_teams(db=mock_db)

        assert len(teams) == 2
        assert teams[0].id == "team-1"
        assert teams[1].id == "team-2"

    def test_get_teams_filters_by_type(self, mock_db):
        """Test get_teams filters by TEAM component type."""
        mock_db.list_components.return_value = ([], None)

        get_teams(db=mock_db)

        mock_db.list_components.assert_called_once_with(component_type=ComponentType.TEAM, exclude_component_ids=None)

    def test_get_teams_with_registry(self, mock_db):
        """Test get_teams passes registry to from_dict."""
        mock_db.list_components.return_value = (
            [{"component_id": "tools-team"}],
            None,
        )
        mock_db.get_config.return_value = {"config": {"id": "tools-team", "tools": [{"name": "search"}]}}

        mock_registry = MagicMock()
        mock_registry.rehydrate_function.return_value = MagicMock()

        teams = get_teams(db=mock_db, registry=mock_registry)

        assert len(teams) == 1

    def test_get_teams_returns_empty_list_on_error(self, mock_db):
        """Test get_teams returns empty list on error."""
        mock_db.list_components.side_effect = Exception("DB error")

        teams = get_teams(db=mock_db)

        assert teams == []

    def test_get_teams_skips_invalid_configs(self, mock_db):
        """Test get_teams skips teams with invalid configs."""
        mock_db.list_components.return_value = (
            [
                {"component_id": "valid-team"},
                {"component_id": "invalid-team"},
            ],
            None,
        )
        mock_db.get_config.side_effect = [
            {"config": {"id": "valid-team", "name": "Valid"}},
            {"config": None},  # Invalid config
        ]

        teams = get_teams(db=mock_db)

        assert len(teams) == 1
        assert teams[0].id == "valid-team"

    def test_get_teams_sets_db_on_all_teams(self, mock_db):
        """Test get_teams sets db on all returned teams via registry."""
        # The db is set via registry lookup when config contains a serialized db reference
        mock_db.id = "test-db"
        mock_db.list_components.return_value = (
            [{"component_id": "team-1"}],
            None,
        )
        mock_db.get_config.return_value = {
            "config": {
                "id": "team-1",
                "name": "Team 1",
                "db": {"type": "postgres", "id": "test-db"},
            }
        }

        # Create registry with the mock db registered
        registry = Registry(dbs=[mock_db])

        teams = get_teams(db=mock_db, registry=registry)

        assert len(teams) == 1
        assert teams[0].db == mock_db
