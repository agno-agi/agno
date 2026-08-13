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
from agno.db.base import BaseDb, ComponentType, ComponentVersionGuard
from agno.db.sqlite import SqliteDb
from agno.registry import Registry
from agno.session import TeamSession
from agno.team.team import Team, get_team_by_id, get_teams

# =============================================================================
# Fixtures
# =============================================================================


def _corrupt_delete_config_row(db: SqliteDb, component_id: str, version: int) -> None:
    """Simulate an externally corrupted pin without weakening the public API."""
    configs_table = db._get_table(table_type="component_configs")
    assert configs_table is not None
    with db.Session() as session:
        result = session.execute(
            configs_table.delete().where(
                configs_table.c.component_id == component_id,
                configs_table.c.version == version,
            )
        )
        session.commit()
    assert result.rowcount == 1


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
    db.component_catalog_api_version = 2

    # Configure common mock methods
    db.get_component = MagicMock(return_value=None)
    db.create_component_with_config = MagicMock(return_value=({"component_id": "test-team"}, {"version": 1}))
    db.upsert_component = MagicMock()
    db.upsert_config = MagicMock(return_value={"version": 1})
    db.delete_component = MagicMock(return_value=True)
    db.get_config = MagicMock()
    db.get_current_config = db.get_config
    db.get_latest_config = db.get_config
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

    def test_to_dict_records_owning_toolkit(self):
        """Functions flattened from a toolkit carry the toolkit's name so
        rehydration can re-bind same-named functions to the right toolkit
        (see Registry.rehydrate_function). Plain tools stay unqualified."""
        from agno.tools.toolkit import Toolkit

        def read_file(path: str) -> str:
            """Read a file."""
            return path

        def plain_tool(x: int) -> int:
            """A plain callable tool."""
            return x

        toolkit = Toolkit(name="agent_files", tools=[read_file])
        team = Team(
            id="toolkit-team",
            members=[],
            tools=[toolkit, plain_tool],
        )

        config = team.to_dict()

        tools_by_name = {t["name"]: t for t in config["tools"]}
        assert tools_by_name["read_file"]["toolkit"] == "agent_files"
        assert "toolkit" not in tools_by_name["plain_tool"]

    def test_to_dict_round_trip_preserves_toolkit(self):
        """A rehydrated team holds bare Functions, not Toolkits; their
        owning_toolkit re-stamps the "toolkit" key so the attribution
        survives load -> save (e.g. a Studio edit)."""
        from agno.registry import Registry
        from agno.tools.toolkit import Toolkit

        def read_file(path: str) -> str:
            """Read a file."""
            return path

        toolkit = Toolkit(name="agent_files", tools=[read_file])
        team = Team(id="round-trip-team", members=[], tools=[toolkit])
        registry = Registry(tools=[toolkit])

        config = team.to_dict()
        assert config["tools"][0]["toolkit"] == "agent_files"

        loaded = Team.from_dict(config, registry=registry)
        assert loaded.tools[0].entrypoint is read_file

        config_resaved = loaded.to_dict()

        tools_by_name = {t["name"]: t for t in config_resaved["tools"]}
        assert tools_by_name["read_file"]["toolkit"] == "agent_files"

    def test_to_dict_serializes_per_get_functions(self):
        """The team serializer reads get_functions() -- what the team runtime
        exposes -- so a toolkit subclass hiding a member never persists it."""
        from agno.tools.toolkit import Toolkit

        def only_a(x: str) -> str:
            """Tool a."""
            return x

        def _make_search(tag):
            def search(q: str) -> str:
                """Search."""
                return f"{tag}:{q}"

            return search

        class GatedToolkit(Toolkit):
            def get_functions(self):
                return {name: f for name, f in self.functions.items() if name != "search"}

        alpha = GatedToolkit(name="alpha", tools=[only_a, _make_search("alpha")])
        beta = Toolkit(name="beta", tools=[_make_search("beta")])
        team = Team(id="gated-team", members=[], tools=[alpha, beta])

        config = team.to_dict()

        serialized = {(t["name"], t.get("toolkit")) for t in config["tools"]}
        assert serialized == {("only_a", "alpha"), ("search", "beta")}


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
        from agno.models.openai import OpenAIResponses

        config = {
            "id": "model-team",
            "name": "Model Team",
            "model": {"provider": "openai", "id": "gpt-4o-mini"},
        }

        team = Team.from_dict(config)

        assert team.model is not None
        assert isinstance(team.model, OpenAIResponses)
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
        """from_dict rehydrates the whole tools list in ONE batch call, so a
        component load shares a single lookup-rebuild budget."""
        tool_dicts = [
            {"name": "search", "description": "Search the web"},
            {"name": "read_file", "description": "Read a file"},
            {"name": "write_file", "description": "Write a file"},
        ]
        config = {"id": "tools-team", "tools": list(tool_dicts)}

        mock_registry = MagicMock()
        mock_tools = [MagicMock(), MagicMock(), MagicMock()]
        mock_registry.rehydrate_functions.return_value = mock_tools

        team = Team.from_dict(config, registry=mock_registry)

        mock_registry.rehydrate_functions.assert_called_once_with(tool_dicts, strict=False)
        assert team.tools == mock_tools

    def test_from_dict_without_registry_raises_for_tools(self):
        """Test from_dict fails loudly when tools cannot be rehydrated."""
        from agno.exceptions import ComponentRehydrationError

        config = {
            "id": "no-registry-team",
            "tools": [{"name": "search", "description": "Search", "parameters": {"type": "object", "properties": {}}}],
        }

        with pytest.raises(ComponentRehydrationError, match="need a registry"):
            Team.from_dict(config, strict=True)

    def test_from_dict_without_registry_keeps_registry_free_tools_when_lenient(self):
        """A lenient load without a registry keeps everything that carries
        itself: provider dicts unchanged, serialized Functions rebuilt without
        entrypoints, bare references as-is with a warning. Deleting them made
        the default load LOSSIER than strict."""
        from agno.tools.function import Function

        provider_tool = {"type": "web_search_preview"}
        function_tool = {"name": "search", "description": "S", "parameters": {"type": "object", "properties": {}}}
        config = {
            "id": "no-registry-team",
            "tools": [provider_tool, function_tool],
        }

        team = Team.from_dict(config, strict=False)

        assert team.tools is not None and len(team.tools) == 2
        assert team.tools[0] == provider_tool
        assert isinstance(team.tools[1], Function) and team.tools[1].entrypoint is None

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

            team = Team.from_dict(config, db=mock_db, strict=True)

            mock_get_agent.assert_called_once_with(id="agent-1", db=mock_db, version=None, registry=None, strict=True)
            assert team.members == [mock_agent]

    def test_from_dict_falls_back_to_registry_for_member_agent(self, mock_db, member_agent):
        """Test from_dict resolves a code-defined member agent via the registry.

        Regression test for teams created via the AgentOS UI whose members are
        code-defined agents (not persisted as DB components). The DB lookup
        returns None, so the registry fallback must find the agent instead of
        silently dropping it.
        """
        config = {
            "id": "members-team",
            "members": [{"type": "agent", "agent_id": "member-agent"}],
        }
        registry = Registry(agents=[member_agent])

        # DB has no such component -> get_agent_by_id returns None
        with patch("agno.agent.get_agent_by_id", return_value=None):
            team = Team.from_dict(config, db=mock_db, registry=registry)

        assert len(team.members) == 1
        assert team.members[0].id == "member-agent"
        # A deep copy is used so the shared registry singleton is not mutated on run
        assert team.members[0] is not member_agent

    def test_from_dict_member_registry_fallback_without_db(self, member_agent):
        """Test from_dict resolves a registry member even when db is None."""
        config = {
            "id": "members-team",
            "members": [{"type": "agent", "agent_id": "member-agent"}],
        }
        registry = Registry(agents=[member_agent])

        team = Team.from_dict(config, db=None, registry=registry)

        assert len(team.members) == 1
        assert team.members[0].id == "member-agent"
        assert team.members[0] is not member_agent

    def test_from_dict_unknown_member_raises(self, mock_db):
        """Test from_dict fails loudly for a member in neither db nor registry."""
        from agno.exceptions import ComponentRehydrationError

        config = {
            "id": "members-team",
            "members": [{"type": "agent", "agent_id": "ghost-agent"}],
        }
        registry = Registry(agents=[])

        with patch("agno.agent.get_agent_by_id", return_value=None):
            with pytest.raises(ComponentRehydrationError, match="ghost-agent"):
                Team.from_dict(config, db=mock_db, registry=registry, strict=True)

    def test_from_dict_unknown_member_is_dropped_when_lenient(self, mock_db):
        """Test strict=False drops a member that is in neither db nor registry."""
        config = {
            "id": "members-team",
            "members": [{"type": "agent", "agent_id": "ghost-agent"}],
        }
        registry = Registry(agents=[])

        with patch("agno.agent.get_agent_by_id", return_value=None):
            team = Team.from_dict(config, db=mock_db, registry=registry, strict=False)

        assert team.members == []

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

    def test_save_creates_component_and_initial_config_atomically(self, basic_team, mock_db):
        """Test first save creates the component and config together."""
        basic_team.db = mock_db
        version = basic_team.save()

        call_args = mock_db.create_component_with_config.call_args
        assert call_args.kwargs["component_id"] == "test-team"
        assert call_args.kwargs["component_type"] == ComponentType.TEAM
        assert call_args.kwargs["name"] == "Test Team"
        assert call_args.kwargs["description"] == "A test team for unit testing"
        assert call_args.kwargs["config"]["id"] == "test-team"
        mock_db.upsert_component.assert_not_called()
        mock_db.upsert_config.assert_not_called()
        assert version == 1

    def test_existing_save_upserts_config_with_projection(self, basic_team, mock_db):
        """Test a published save updates config and projection together."""
        mock_db.get_component.return_value = {
            "component_id": "test-team",
            "component_type": "team",
            "deleted_at": None,
        }
        mock_db.upsert_config.return_value = {"version": 2}
        guard = ComponentVersionGuard(latest_version=1, current_version=1)

        basic_team.db = mock_db
        version = basic_team.save(guard=guard)

        mock_db.upsert_config.assert_called_once()
        call_args = mock_db.upsert_config.call_args
        assert call_args.kwargs["component_id"] == "test-team"
        assert call_args.kwargs["guard"] == guard
        assert "config" in call_args.kwargs
        assert call_args.kwargs["projection"] == {
            "name": "Test Team",
            "description": "A test team for unit testing",
            "metadata": None,
        }
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

        # Check that links were committed with the initial config
        call_args = mock_db.create_component_with_config.call_args
        links = call_args.kwargs.get("links")
        assert links is not None
        assert len(links) == 1
        assert links[0]["link_kind"] == "member"
        assert links[0]["child_component_id"] == "member-agent"
        assert links[0]["child_version"] == 5
        assert links[0]["meta"]["type"] == "agent"

    def test_save_with_explicit_db(self, basic_team, mock_db):
        """Test save uses explicitly provided db."""
        version = basic_team.save(db=mock_db)

        mock_db.create_component_with_config.assert_called_once()
        mock_db.upsert_component.assert_not_called()
        mock_db.upsert_config.assert_not_called()
        assert version == 1

    def test_save_with_label(self, basic_team, mock_db):
        """Test first save passes the label to the atomic create."""
        basic_team.db = mock_db
        basic_team.save(label="production")

        call_args = mock_db.create_component_with_config.call_args
        assert call_args.kwargs["label"] == "production"

    def test_save_with_stage(self, basic_team, mock_db):
        """Test first save passes the stage to the atomic create."""
        basic_team.db = mock_db
        basic_team.save(stage="draft")

        call_args = mock_db.create_component_with_config.call_args
        assert call_args.kwargs["stage"] == "draft"

    def test_save_draft_team_with_draft_member_on_real_sqlite(self, tmp_path):
        """A draft composite may pin a draft child; publication validates it later."""
        db = SqliteDb(db_file=str(tmp_path / "draft_team.db"))
        member = Agent(id="draft-member", name="Draft Member")
        team = Team(id="draft-team", name="Draft Team", members=[member], db=db)

        version = team.save(stage="draft")

        assert version == 1
        assert db.get_config("draft-member", version=1)["stage"] == "draft"  # type: ignore[index]
        assert db.get_config("draft-team", version=1)["stage"] == "draft"  # type: ignore[index]
        links = db.get_links("draft-team", 1)
        assert len(links) == 1
        assert links[0]["link_kind"] == "member"
        assert links[0]["link_key"] == "member_0"
        assert links[0]["child_component_id"] == "draft-member"
        assert links[0]["child_version"] == 1
        assert links[0]["meta"] == {"type": "agent"}

    def test_save_without_db_raises_error(self, basic_team):
        """Test save raises error when no db is available."""
        with pytest.raises(ValueError, match="Db not initialized or provided"):
            basic_team.save()

    def test_save_handles_db_error(self, basic_team, mock_db):
        """Test save raises error when database operation fails."""
        mock_db.create_component_with_config.side_effect = Exception("Database error")

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

    def test_load_preserves_registry_members_without_graph_children(self, mock_db, member_agent):
        """Test load keeps registry-resolved members when the graph has no children.

        Code-defined member agents are not DB components, so the loaded graph has
        no children for them. _hydrate_from_graph must not clobber the members
        that from_dict resolved via the registry.
        """
        mock_db.load_component_graph.return_value = {
            "component": {"component_id": "team-with-registry-member"},
            "config": {
                "config": {
                    "id": "team-with-registry-member",
                    "name": "Team",
                    "members": [{"type": "agent", "agent_id": "member-agent"}],
                }
            },
            "children": [],
        }
        registry = Registry(agents=[member_agent])

        with patch("agno.agent.get_agent_by_id", return_value=None):
            team = Team.load(id="team-with-registry-member", db=mock_db, registry=registry)

        assert team is not None
        assert len(team.members) == 1
        assert team.members[0].id == "member-agent"

    def test_load_merges_graph_and_registry_members(self, mock_db, member_agent):
        """Test load merges DB-persisted graph children with registry members."""
        mock_db.load_component_graph.return_value = {
            "component": {"component_id": "mixed-team"},
            "config": {
                "config": {
                    "id": "mixed-team",
                    "name": "Mixed Team",
                    "members": [
                        {"type": "agent", "agent_id": "member-agent"},
                        {"type": "agent", "agent_id": "db-agent"},
                    ],
                }
            },
            "children": [
                {
                    "link": {"meta": {"type": "agent"}},
                    "graph": {
                        "component": {"component_id": "db-agent"},
                        "config": {"config": {"id": "db-agent", "name": "DB Agent"}},
                    },
                }
            ],
        }
        registry = Registry(agents=[member_agent])

        # DB lookup only resolves the graph-backed member; registry resolves the other
        def fake_get_agent(id, db, version=None, registry=None, strict=True):  # noqa: A002
            if id == "db-agent":
                agent = Agent(id="db-agent", name="DB Agent")
                return agent
            return None

        with patch("agno.agent.get_agent_by_id", side_effect=fake_get_agent):
            team = Team.load(id="mixed-team", db=mock_db, registry=registry)

        assert team is not None
        member_ids = [m.id for m in team.members]
        assert "member-agent" in member_ids
        assert "db-agent" in member_ids
        assert len(team.members) == 2

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

    def test_load_round_trips_on_real_sqlite_db(self, tmp_path):
        """Test save/load round-trips on a real SqliteDb.

        The mock_db fixture accepts any call signature, so only a real backend
        catches an override whose signature diverges from BaseDb (SqliteDb's
        load_component_graph rejected the label kwarg that load() always passes).
        """
        db = SqliteDb(db_file=str(tmp_path / "team_load.db"))
        team = Team(id="rt-team", name="Round Trip Team", members=[Agent(id="rt-agent", name="Round Trip Agent")])
        team.save(db=db)

        loaded = Team.load(id="rt-team", db=db)

        assert loaded is not None
        assert loaded.id == "rt-team"
        assert loaded.name == "Round Trip Team"
        assert len(loaded.members) == 1
        assert loaded.members[0].id == "rt-agent"

    def test_get_team_by_id_honors_pinned_member_versions(self, tmp_path):
        """get_team_by_id must load members at the version pinned by the team's
        links, like the graph loader does, not at the member's current version."""
        db = SqliteDb(db_file=str(tmp_path / "team_pin.db"))

        member = Agent(id="pin-agent", name="Pin Agent", description="v1 description")
        team = Team(id="pin-team", name="Pin Team", members=[member])
        team.save(db=db)

        # Publish a newer member version after the team pinned the old one
        member.description = "v2 description"
        member.save(db=db)

        graph_loaded = Team.load(id="pin-team", db=db)
        by_id_loaded = get_team_by_id(db=db, id="pin-team")

        assert graph_loaded is not None
        assert graph_loaded.members[0].description == "v1 description"
        assert by_id_loaded is not None
        assert by_id_loaded.members[0].description == "v1 description"

    def test_load_passes_registry_to_graph_members(self, tmp_path):
        """Members hydrated from the component graph must receive the registry
        so their tools survive a load."""
        from agno.models.openai import OpenAIChat

        def search(query: str) -> str:
            """Search for a query."""
            return f"results for {query}"

        db = SqliteDb(db_file=str(tmp_path / "team_tools.db"))
        member = Agent(id="tool-agent", name="Tool Agent", model=OpenAIChat(id="gpt-4o-mini"), tools=[search])
        team = Team(id="tool-team", name="Tool Team", members=[member])
        team.save(db=db)

        loaded = Team.load(id="tool-team", db=db, registry=Registry(tools=[search]))

        assert loaded is not None
        loaded_member = loaded.members[0]
        assert loaded_member.tools, "graph-hydrated member lost its tools"
        assert loaded_member.tools[0].entrypoint is search

    def test_load_rehydrates_member_agent_tools(self, tmp_path):
        """A member agent's tools must be rehydrated against the same registry
        the team was loaded with. Without it Agent.from_dict takes its
        no-registry branch, drops the tools outright, and the member comes back
        with none -- the nested-team branch already forwards the registry."""
        from agno.models.openai import OpenAIResponses
        from agno.tools.toolkit import Toolkit

        def search_web(query: str) -> str:
            """Search the web."""
            return "results"

        toolkit = Toolkit(
            name="web",
            tools=[search_web],
            instructions="Cite every source.",
            add_instructions=True,
        )
        model = OpenAIResponses(id="gpt-5.5")
        db = SqliteDb(db_file=str(tmp_path / "team_member_tools.db"))
        member = Agent(id="member", name="Member", model=model, tools=[toolkit])
        Team(id="tool-team", name="Tool Team", model=model, members=[member]).save(db=db)

        loaded = Team.load(id="tool-team", db=db, registry=Registry(tools=[toolkit], models=[model]))

        assert loaded is not None
        member_tools = loaded.members[0].tools or []
        assert [tool.name for tool in member_tools] == ["search_web"]
        assert member_tools[0].entrypoint is not None
        # And the toolkit came with them, so its guidance survives the reload.
        assert member_tools[0].source_toolkit is toolkit

    def test_load_passes_member_provider_dict_tools_through(self, tmp_path):
        """Provider-run tools persist as plain dicts, typed builtins and
        untyped custom shapes alike. Rehydrating one as a Function config
        raised a ValidationError that took the whole team load down; they must
        ride through the member's tools untouched instead."""
        from agno.models.openai import OpenAIResponses

        provider_dicts = [
            {"type": "web_search"},
            {"name": "get_weather", "description": "Weather", "input_schema": {"type": "object"}},
        ]
        model = OpenAIResponses(id="gpt-5.5")
        db = SqliteDb(db_file=str(tmp_path / "team_builtin_tools.db"))
        member = Agent(id="builtin-member", name="Member", model=model, tools=list(provider_dicts))
        Team(id="builtin-team", name="Builtin Team", model=model, members=[member]).save(db=db)

        loaded = Team.load(id="builtin-team", db=db, registry=Registry(models=[model]))

        assert loaded is not None
        assert loaded.members[0].tools == provider_dicts


# =============================================================================
# delete() Tests
# =============================================================================


class TestTeamDelete:
    """Tests for Team.delete() method."""

    def test_delete_calls_delete_component(self, basic_team, mock_db):
        """Test delete calls delete_component."""
        mock_db.delete_component.return_value = True
        guard = ComponentVersionGuard(latest_version=1, current_version=1)

        basic_team.db = mock_db
        result = basic_team.delete(guard=guard)

        mock_db.delete_component.assert_called_once_with(
            component_id="test-team",
            hard_delete=False,
            guard=guard,
            require_no_dependents=True,
            expected_component_type=ComponentType.TEAM,
        )
        assert result is True

    def test_delete_with_hard_delete(self, basic_team, mock_db):
        """Test delete with hard_delete flag."""
        mock_db.delete_component.return_value = True
        guard = ComponentVersionGuard(latest_version=1, current_version=1)

        basic_team.db = mock_db
        result = basic_team.delete(hard_delete=True, guard=guard)

        mock_db.delete_component.assert_called_once_with(
            component_id="test-team",
            hard_delete=True,
            guard=guard,
            require_no_dependents=True,
            expected_component_type=ComponentType.TEAM,
        )
        assert result is True

    def test_delete_can_explicitly_bypass_dependency_check(self, basic_team, mock_db):
        """Test delete forwards the dangerous dependency-check escape hatch."""
        basic_team.db = mock_db
        guard = ComponentVersionGuard(latest_version=1, current_version=1)

        assert basic_team.delete(require_no_dependents=False, guard=guard) is True

        mock_db.delete_component.assert_called_once_with(
            component_id="test-team",
            hard_delete=False,
            guard=guard,
            require_no_dependents=False,
            expected_component_type=ComponentType.TEAM,
        )

    def test_delete_uses_exact_catalog_v1_signature(self, basic_team, mock_db):
        """The v2 dependency keyword must never reach a legacy override."""
        calls = []

        def legacy_delete(component_id, hard_delete=False):
            calls.append((component_id, hard_delete))
            return True

        mock_db.component_catalog_api_version = 1
        mock_db.delete_component = legacy_delete
        basic_team.db = mock_db

        assert basic_team.delete(require_no_dependents=False) is True
        assert calls == [("test-team", False)]

    def test_delete_with_explicit_db(self, basic_team, mock_db):
        """Test delete uses explicitly provided db."""
        mock_db.delete_component.return_value = True

        result = basic_team.delete(
            db=mock_db,
            guard=ComponentVersionGuard(latest_version=1, current_version=1),
        )

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
        result = basic_team.delete(guard=ComponentVersionGuard(latest_version=1, current_version=1))

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
        mock_db.get_config.assert_called_once_with(component_id="found-team", version=None, label=None)

    def test_get_team_by_id_returns_draft_only_team_and_member(self, tmp_path):
        """Draft fallback also applies to an unpinned member loaded by Team.from_dict."""
        db = SqliteDb(db_file=str(tmp_path / "draft-only-team.db"))
        member = Agent(id="draft-member", name="Draft Member", db=db)
        assert member.save(stage="draft") == 1
        assert db.get_current_config("draft-member") is None

        db.upsert_component(
            component_id="draft-team",
            component_type=ComponentType.TEAM,
            name="Draft Team",
        )
        db.upsert_config(
            component_id="draft-team",
            stage="draft",
            config={
                "id": "draft-team",
                "name": "Draft Team",
                "members": [{"type": "agent", "agent_id": "draft-member"}],
            },
        )
        assert db.get_current_config("draft-team") is None

        loaded = get_team_by_id(db=db, id="draft-team")

        assert loaded is not None
        assert loaded.id == "draft-team"
        assert len(loaded.members) == 1
        assert loaded.members[0].id == "draft-member"

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
        mock_registry.rehydrate_functions.return_value = [MagicMock()]

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
        mock_db.get_latest_config = MagicMock(
            side_effect=[
                {"config": {"id": "team-1", "name": "Team 1"}},
                {"config": {"id": "team-2", "name": "Team 2"}},
            ]
        )

        teams = get_teams(db=mock_db)

        assert len(teams) == 2
        assert teams[0].id == "team-1"
        assert teams[1].id == "team-2"
        assert mock_db.get_latest_config.call_count == 2
        mock_db.get_config.assert_not_called()

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
        mock_registry.rehydrate_functions.return_value = [MagicMock()]

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


def test_team_load_survives_broken_current_member_version(tmp_path):
    """Team.load resolves members at the versions pinned by the graph links,
    so a later member version with unresolvable references must not abort the
    load of a team pinned to a clean version."""
    from agno.models.openai import OpenAIChat

    db = SqliteDb(db_file=str(tmp_path / "team_pin_broken.db"))

    member = Agent(id="m1", name="M1")
    team = Team(id="t1", name="T1", members=[member])
    team.save(db=db)

    def search(query: str) -> str:
        """Search for a query."""
        return f"results for {query}"

    # Publish a v2 of the member that needs a registry to rehydrate
    member.model = OpenAIChat(id="gpt-4o-mini")
    member.tools = [search]
    member.save(db=db)

    loaded = Team.load(id="t1", db=db)

    assert loaded is not None
    assert [m.id for m in loaded.members] == ["m1"]


class TestMemberPinFailures:
    def test_strict_pin_miss_refuses_and_names_the_version(self, tmp_path):
        """A pinned member version whose config row was deleted must refuse
        with the pin and the remedy, not report the member as missing."""
        from agno.exceptions import ComponentRehydrationError

        db = SqliteDb(db_file=str(tmp_path / "pin_miss.db"))
        member = Agent(id="pm-member", name="Member")
        Team(id="pm-team", name="Team", members=[member]).save(db=db)
        member.description = "v2"
        member.save(db=db)
        links = db.get_links(component_id="pm-team", version=1)
        pinned = next(link for link in links if link["link_kind"] == "member")["child_version"]
        _corrupt_delete_config_row(db, "pm-member", pinned)

        with pytest.raises(ComponentRehydrationError, match=f"pins member agent 'pm-member' at version {pinned}"):
            get_team_by_id(db=db, id="pm-team", strict=True)

    def test_strict_pin_miss_does_not_substitute_registry_component(self, tmp_path):
        """An explicit pin names one stored version; a same-id registry
        component is a different object and must not silently replace it."""
        from agno.exceptions import ComponentRehydrationError

        db = SqliteDb(db_file=str(tmp_path / "pin_subst.db"))
        member = Agent(id="ps-member", name="Member")
        Team(id="ps-team", name="Team", members=[member]).save(db=db)
        member.description = "v2"
        member.save(db=db)
        links = db.get_links(component_id="ps-team", version=1)
        pinned = next(link for link in links if link["link_kind"] == "member")["child_version"]
        _corrupt_delete_config_row(db, "ps-member", pinned)
        registry = Registry(agents=[Agent(id="ps-member", name="Code Member")])

        with pytest.raises(ComponentRehydrationError, match="pins member agent 'ps-member'"):
            get_team_by_id(db=db, id="ps-team", registry=registry, strict=True)

        # Lenient degrades to the member's current stored version, so the
        # team stays usable without silently substituting the registry object.
        lenient = get_team_by_id(db=db, id="ps-team", registry=registry, strict=False)
        assert lenient.members[0].description == "v2"


def test_from_dict_without_registry_loads_registry_free_tools_under_strict():
    """Provider-native dicts and external-execution tools need no registry, so
    a strict team load without one accepts them."""
    config = {
        "id": "registry-free-team",
        "tools": [
            {"type": "web_search"},
            {
                "name": "charge_card",
                "description": "Charge",
                "parameters": {"type": "object", "properties": {}},
                "external_execution": True,
            },
        ],
    }

    team = Team.from_dict(config, strict=True)

    assert team.tools is not None and len(team.tools) == 2


def test_strict_refuses_a_member_of_unknown_type():
    """A member kind the loader does not model must refuse under strict, not
    silently dispatch a reduced team."""
    from agno.exceptions import ComponentRehydrationError

    config = {
        "id": "future-team",
        "members": [{"type": "future-member", "future_id": "x"}],
    }

    with pytest.raises(ComponentRehydrationError, match="future-member"):
        Team.from_dict(config, strict=True)

    lenient = Team.from_dict(config, strict=False)
    assert lenient.members == []


def test_strict_refuses_a_wrong_type_registry_copy():
    """A custom deep_copy returning the wrong type must refuse under strict,
    not dispatch the impostor."""
    from agno.exceptions import ComponentRehydrationError

    class ImposterAgent(Agent):
        def deep_copy(self, *, update=None):
            return object()

    registry = Registry(agents=[ImposterAgent(id="imp", name="Imp")])
    config = {"id": "imp-team", "members": [{"type": "agent", "agent_id": "imp"}]}

    with pytest.raises(ComponentRehydrationError, match="not a Agent|not an Agent|object"):
        Team.from_dict(config, registry=registry, strict=True)


def test_strict_refuses_a_copy_that_lost_serialized_state():
    """A subclass whose __init__ swallows kwargs turns the inherited deep_copy
    into an empty shell; strict must refuse the lossy copy, not dispatch it."""
    from agno.exceptions import ComponentRehydrationError

    class PolicyAgent(Agent):
        def __init__(self, *args, policy=None, **kwargs):
            super().__init__(*args, **kwargs)
            self.policy = policy

    registry = Registry(agents=[PolicyAgent(id="pol", name="Pol", instructions="policy says", policy="strict")])
    config = {"id": "pol-team", "members": [{"type": "agent", "agent_id": "pol"}]}

    with pytest.raises(ComponentRehydrationError, match="lost state"):
        Team.from_dict(config, registry=registry, strict=True)


def test_team_provider_envelope_tools_survive_save_and_strict_reload(tmp_path):
    """Team's serializer must keep provider-native dict tools, so an envelope
    that rides through a load is not destroyed by the next save."""
    from agno.db.sqlite import SqliteDb
    from agno.models.openai import OpenAIResponses

    db = SqliteDb(db_file=str(tmp_path / "team_envelope.db"))
    envelope = {"type": "web_search_preview"}
    team = Team(id="env-team", name="T", model=OpenAIResponses(id="gpt-5.5"), members=[], tools=[envelope])
    team.save(db=db)

    stored = db.get_config(component_id="env-team")["config"]
    assert stored.get("tools") == [envelope]

    loaded = get_team_by_id(db=db, id="env-team", registry=Registry(dbs=[db]), strict=True)
    assert loaded is not None
    assert loaded.tools == [envelope]

    # And a load-save cycle keeps it too.
    loaded.save(db=db)
    assert db.get_config(component_id="env-team")["config"].get("tools") == [envelope]
