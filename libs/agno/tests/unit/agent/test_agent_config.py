"""
Unit tests for Agent configuration serialization and persistence.

Tests cover:
- to_dict(): Serialization of agent to dictionary
- from_dict(): Deserialization of agent from dictionary
- save(): Saving agent to database
- load(): Loading agent from database
- delete(): Deleting agent from database
- get_agent_by_id(): Helper function to get agent by ID
- get_agents(): Helper function to get all agents
"""

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from agno.agent.agent import Agent, get_agent_by_id, get_agents
from agno.db.base import BaseDb, ComponentType, ComponentVersionGuard
from agno.registry import Registry

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
    db.component_catalog_api_version = 2

    # Configure common mock methods
    db.get_component = MagicMock(return_value=None)
    db.create_component_with_config = MagicMock(return_value=({"component_id": "test-agent"}, {"version": 1}))
    db.upsert_component = MagicMock()
    db.upsert_config = MagicMock(return_value={"version": 1})
    db.delete_component = MagicMock(return_value=True)
    db.get_config = MagicMock()
    db.get_current_config = db.get_config
    db.get_latest_config = db.get_config
    db.list_components = MagicMock()
    db.to_dict = MagicMock(return_value={"type": "postgres", "id": "test-db"})

    return db


@pytest.fixture
def basic_agent():
    """Create a basic agent for testing."""
    return Agent(
        id="test-agent",
        name="Test Agent",
        description="A test agent for unit testing",
    )


@pytest.fixture
def agent_with_model():
    """Create an agent with a real model for testing to_dict."""
    # Use a real model class with mocked internals for serialization testing
    from agno.models.openai import OpenAIChat

    model = OpenAIChat(id="gpt-4o-mini")
    agent = Agent(
        id="model-agent",
        name="Model Agent",
        model=model,
    )
    return agent


@pytest.fixture
def agent_with_settings():
    """Create an agent with various settings configured."""
    return Agent(
        id="settings-agent",
        name="Settings Agent",
        description="Agent with many settings",
        instructions="Be helpful and concise",
        markdown=True,
        debug_mode=True,
        retries=3,
        tool_call_limit=10,
        num_history_runs=5,
        add_history_to_context=True,
        add_datetime_to_context=True,
    )


@pytest.fixture
def sample_agent_config() -> Dict[str, Any]:
    """Sample agent configuration dictionary."""
    return {
        "id": "sample-agent",
        "name": "Sample Agent",
        "description": "A sample agent",
        "instructions": "Be helpful",
        "markdown": True,
        "model": {"provider": "openai", "id": "gpt-4o-mini"},
    }


# =============================================================================
# to_dict() Tests
# =============================================================================


class TestAgentToDict:
    """Tests for Agent.to_dict() method."""

    def test_to_dict_basic_agent(self, basic_agent):
        """Test to_dict with a basic agent."""
        config = basic_agent.to_dict()

        assert config["id"] == "test-agent"
        assert config["name"] == "Test Agent"
        assert config["description"] == "A test agent for unit testing"

    def test_to_dict_with_model(self, agent_with_model):
        """Test to_dict includes model configuration."""
        config = agent_with_model.to_dict()

        assert "model" in config
        assert config["model"]["provider"] == "OpenAI"
        assert config["model"]["id"] == "gpt-4o-mini"

    def test_to_dict_with_settings(self, agent_with_settings):
        """Test to_dict preserves all settings."""
        config = agent_with_settings.to_dict()

        assert config["id"] == "settings-agent"
        assert config["name"] == "Settings Agent"
        assert config["description"] == "Agent with many settings"
        assert config["instructions"] == "Be helpful and concise"
        assert config["markdown"] is True
        assert config["debug_mode"] is True
        assert config["retries"] == 3
        assert config["tool_call_limit"] == 10
        assert config["num_history_runs"] == 5
        assert config["add_history_to_context"] is True
        assert config["add_datetime_to_context"] is True

    def test_to_dict_excludes_default_values(self):
        """Test that default values are not included in the config."""
        agent = Agent(id="minimal-agent")
        config = agent.to_dict()

        # Default values should not be present
        assert "markdown" not in config  # defaults to False
        assert "debug_mode" not in config  # defaults to False
        assert "retries" not in config  # defaults to 0
        assert "add_history_to_context" not in config  # defaults to False
        assert "store_history_messages" not in config  # defaults to False

    def test_to_dict_includes_store_history_messages_when_true(self):
        """Test that store_history_messages=True is serialized."""
        agent = Agent(id="history-agent", store_history_messages=True)
        config = agent.to_dict()

        assert "store_history_messages" in config
        assert config["store_history_messages"] is True

    def test_to_dict_with_db(self, basic_agent, mock_db):
        """Test to_dict includes database configuration."""
        basic_agent.db = mock_db
        config = basic_agent.to_dict()

        assert "db" in config
        assert config["db"] == {"type": "postgres", "id": "test-db"}

    def test_to_dict_with_instructions_list(self):
        """Test to_dict handles instructions as a list."""
        agent = Agent(
            id="list-instructions-agent",
            instructions=["Step 1: Do this", "Step 2: Do that"],
        )
        config = agent.to_dict()

        assert config["instructions"] == ["Step 1: Do this", "Step 2: Do that"]

    def test_to_dict_with_system_message(self):
        """Test to_dict includes system message when it's a string."""
        agent = Agent(
            id="system-message-agent",
            system_message="You are a helpful assistant.",
        )
        config = agent.to_dict()

        assert config["system_message"] == "You are a helpful assistant."

    def test_to_dict_with_metadata(self):
        """Test to_dict includes metadata."""
        agent = Agent(
            id="metadata-agent",
            metadata={"version": "1.0", "author": "test"},
        )
        config = agent.to_dict()

        assert config["metadata"] == {"version": "1.0", "author": "test"}

    def test_to_dict_with_user_and_session(self):
        """Test to_dict includes user and session settings."""
        agent = Agent(
            id="session-agent",
            user_id="user-123",
            session_id="session-456",
        )
        config = agent.to_dict()

        assert config["user_id"] == "user-123"
        assert config["session_id"] == "session-456"

    def test_to_dict_records_owning_toolkit(self):
        """Functions flattened from a toolkit carry the toolkit's name so
        rehydration can re-bind same-named functions to the right toolkit
        (see Registry.rehydrate_function). Plain tools stay unqualified."""
        from agno.models.openai import OpenAIChat
        from agno.tools.toolkit import Toolkit

        def read_file(path: str) -> str:
            """Read a file."""
            return path

        def write_file(path: str, content: str) -> str:
            """Write a file."""
            return path

        def plain_tool(x: int) -> int:
            """A plain callable tool."""
            return x

        toolkit = Toolkit(name="agent_files", tools=[read_file, write_file])
        agent = Agent(
            id="toolkit-agent",
            model=OpenAIChat(id="gpt-4o-mini"),
            tools=[toolkit, plain_tool],
        )

        config = agent.to_dict()

        tools_by_name = {t["name"]: t for t in config["tools"]}
        assert tools_by_name["read_file"]["toolkit"] == "agent_files"
        assert tools_by_name["write_file"]["toolkit"] == "agent_files"
        assert "toolkit" not in tools_by_name["plain_tool"]

    def test_to_dict_round_trip_preserves_toolkit(self):
        """A rehydrated agent holds bare Functions, not Toolkits; their
        owning_toolkit re-stamps the "toolkit" key so the attribution
        survives load -> save (e.g. a Studio edit)."""
        from agno.models.openai import OpenAIChat
        from agno.registry import Registry
        from agno.tools.toolkit import Toolkit

        def read_file(path: str) -> str:
            """Read a file."""
            return path

        toolkit = Toolkit(name="agent_files", tools=[read_file])
        agent = Agent(
            id="round-trip-agent",
            model=OpenAIChat(id="gpt-4o-mini"),
            tools=[toolkit],
        )
        registry = Registry(tools=[toolkit])

        config = agent.to_dict()
        assert config["tools"][0]["toolkit"] == "agent_files"

        loaded = Agent.from_dict(config, registry=registry)
        assert loaded.tools[0].entrypoint is read_file

        config_resaved = loaded.to_dict()

        tools_by_name = {t["name"]: t for t in config_resaved["tools"]}
        assert tools_by_name["read_file"]["toolkit"] == "agent_files"

    def test_to_dict_stamps_toolkit_per_get_functions(self):
        """The stamping walk reads get_functions() -- what parse_tools
        actually serializes -- so a toolkit subclass exposing a subset never
        claims a name it hides."""
        from agno.models.openai import OpenAIChat
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
        agent = Agent(
            id="gated-agent",
            model=OpenAIChat(id="gpt-4o-mini"),
            tools=[alpha, beta],
        )

        config = agent.to_dict()

        tools_by_name = {t["name"]: t for t in config["tools"]}
        assert tools_by_name["only_a"]["toolkit"] == "alpha"
        assert tools_by_name["search"]["toolkit"] == "beta"


# =============================================================================
# from_dict() Tests
# =============================================================================


class TestAgentFromDict:
    """Tests for Agent.from_dict() method."""

    def test_from_dict_basic(self, sample_agent_config):
        """Test from_dict creates agent with basic config."""
        # Remove model to avoid model lookup
        config = sample_agent_config.copy()
        del config["model"]

        agent = Agent.from_dict(config)

        assert agent.id == "sample-agent"
        assert agent.name == "Sample Agent"
        assert agent.description == "A sample agent"
        assert agent.instructions == "Be helpful"
        assert agent.markdown is True

    def test_from_dict_with_model(self):
        """Test from_dict reconstructs model from config."""
        from agno.models.openai import OpenAIResponses

        config = {
            "id": "model-agent",
            "name": "Model Agent",
            "model": {"provider": "openai", "id": "gpt-4o-mini"},
        }

        # from_dict should reconstruct the model from the config
        agent = Agent.from_dict(config)

        # Model should be reconstructed
        assert agent.model is not None
        assert isinstance(agent.model, OpenAIResponses)
        assert agent.model.id == "gpt-4o-mini"

    def test_from_dict_preserves_settings(self):
        """Test from_dict preserves all settings."""
        config = {
            "id": "full-agent",
            "name": "Full Agent",
            "debug_mode": True,
            "retries": 3,
            "tool_call_limit": 10,
            "num_history_runs": 5,
            "add_history_to_context": True,
            "add_datetime_to_context": True,
        }

        agent = Agent.from_dict(config)

        assert agent.debug_mode is True
        assert agent.retries == 3
        assert agent.tool_call_limit == 10
        assert agent.num_history_runs == 5
        assert agent.add_history_to_context is True
        assert agent.add_datetime_to_context is True

    def test_from_dict_with_db_postgres(self):
        """Test from_dict reconstructs PostgresDb."""
        config = {
            "id": "db-agent",
            "db": {"type": "postgres", "db_url": "postgresql://localhost/test"},
        }

        with patch("agno.db.postgres.PostgresDb.from_dict") as mock_from_dict:
            mock_db = MagicMock()
            mock_from_dict.return_value = mock_db

            agent = Agent.from_dict(config)

            mock_from_dict.assert_called_once()
            assert agent.db == mock_db

    def test_from_dict_with_db_sqlite(self):
        """Test from_dict reconstructs SqliteDb."""
        config = {
            "id": "sqlite-agent",
            "db": {"type": "sqlite", "db_file": "/tmp/test.db"},
        }

        with patch("agno.db.sqlite.SqliteDb.from_dict") as mock_from_dict:
            mock_db = MagicMock()
            mock_from_dict.return_value = mock_db

            agent = Agent.from_dict(config)

            mock_from_dict.assert_called_once()
            assert agent.db == mock_db

    def test_from_dict_with_registry_tools(self):
        """from_dict rehydrates the whole tools list in ONE batch call, so a
        component load shares a single lookup-rebuild budget."""
        tool_dicts = [
            {"name": "search", "description": "Search the web"},
            {"name": "read_file", "description": "Read a file"},
            {"name": "write_file", "description": "Write a file"},
        ]
        config = {"id": "tools-agent", "tools": list(tool_dicts)}

        mock_registry = MagicMock()
        mock_tools = [MagicMock(), MagicMock(), MagicMock()]
        mock_registry.rehydrate_functions.return_value = mock_tools

        agent = Agent.from_dict(config, registry=mock_registry)

        mock_registry.rehydrate_functions.assert_called_once_with(tool_dicts, strict=False)
        assert agent.tools == mock_tools

    def test_from_dict_without_registry_raises_for_tools(self):
        """Test from_dict fails loudly when tools cannot be rehydrated."""
        from agno.exceptions import ComponentRehydrationError

        config = {
            "id": "no-registry-agent",
            "tools": [{"name": "search", "description": "Search", "parameters": {"type": "object", "properties": {}}}],
        }

        with pytest.raises(ComponentRehydrationError, match="need a registry"):
            Agent.from_dict(config, strict=True)

    def test_from_dict_without_registry_loads_registry_free_tools_under_strict(self):
        """Provider-native dicts and external-execution tools need no registry,
        so a strict load without one accepts them - identical to an empty
        Registry."""
        config = {
            "id": "registry-free-agent",
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

        agent = Agent.from_dict(config, strict=True)

        assert agent.tools is not None and len(agent.tools) == 2

    def test_from_dict_missing_tool_in_registry_raises(self):
        """Test from_dict fails loudly when the registry lacks a referenced tool."""
        from agno.exceptions import ComponentRehydrationError

        config = {
            "id": "missing-tool-agent",
            "tools": [{"name": "search", "parameters": {"type": "object", "properties": {}}}],
        }

        with pytest.raises(ComponentRehydrationError, match="search"):
            Agent.from_dict(config, registry=Registry(), strict=True)

    def test_from_dict_without_registry_keeps_registry_free_tools_when_lenient(self):
        """A lenient load without a registry keeps everything that carries
        itself: provider dicts unchanged, serialized Functions rebuilt without
        entrypoints, bare references as-is with a warning. Deleting them made
        the default load LOSSIER than strict."""
        from agno.tools.function import Function

        provider_tool = {"type": "web_search_preview"}
        function_tool = {"name": "search", "description": "S", "parameters": {"type": "object", "properties": {}}}
        config = {
            "id": "no-registry-agent",
            "tools": [provider_tool, function_tool],
        }

        agent = Agent.from_dict(config, strict=False)

        assert agent.tools is not None and len(agent.tools) == 2
        assert agent.tools[0] == provider_tool
        assert isinstance(agent.tools[1], Function) and agent.tools[1].entrypoint is None

    def test_from_dict_roundtrip(self, agent_with_settings):
        """Test that to_dict -> from_dict preserves agent configuration."""
        config = agent_with_settings.to_dict()
        reconstructed = Agent.from_dict(config)

        assert reconstructed.id == agent_with_settings.id
        assert reconstructed.name == agent_with_settings.name
        assert reconstructed.description == agent_with_settings.description
        assert reconstructed.markdown == agent_with_settings.markdown
        assert reconstructed.debug_mode == agent_with_settings.debug_mode
        assert reconstructed.retries == agent_with_settings.retries

    def test_from_dict_roundtrip_store_history_messages_true(self):
        """Test that store_history_messages=True survives to_dict/from_dict round-trip."""
        agent = Agent(id="roundtrip-agent", store_history_messages=True)
        config = agent.to_dict()
        reconstructed = Agent.from_dict(config)

        assert reconstructed.store_history_messages is True

    def test_from_dict_roundtrip_store_history_messages_false(self):
        """Test that store_history_messages=False (default) survives round-trip."""
        agent = Agent(id="roundtrip-agent-default", store_history_messages=False)
        config = agent.to_dict()
        reconstructed = Agent.from_dict(config)

        assert reconstructed.store_history_messages is False


# =============================================================================
# Knowledge serialization / deserialization Tests
# =============================================================================


class TestAgentKnowledgeRoundtrip:
    """Tests for knowledge being stored as a registry reference and resolved on load."""

    def _make_knowledge(self, name="Docs KB"):
        from agno.knowledge.knowledge import Knowledge

        # contents_db is required for the OS to treat it as a real instance,
        # but for serialization we only need a name. vector_db is mocked.
        return Knowledge(name=name, vector_db=MagicMock())

    def test_to_dict_stores_knowledge_reference_by_name(self):
        """to_dict serializes knowledge as a {'name': ...} reference, not the object."""
        kb = self._make_knowledge("Docs KB")
        agent = Agent(id="kb-agent", knowledge=kb)

        config = agent.to_dict()

        assert config["knowledge"] == {"name": "Docs KB"}

    def test_to_dict_skips_knowledge_without_name(self):
        """Knowledge without a name cannot be referenced and is not serialized."""
        kb = self._make_knowledge(name=None)
        agent = Agent(id="kb-agent", knowledge=kb)

        config = agent.to_dict()

        assert "knowledge" not in config

    def test_from_dict_resolves_knowledge_from_registry(self):
        """from_dict resolves the knowledge reference back to the registry instance."""
        kb = self._make_knowledge("Docs KB")
        agent = Agent(id="kb-agent", knowledge=kb, search_knowledge=True)
        config = agent.to_dict()

        registry = Registry(knowledge=[kb])
        reconstructed = Agent.from_dict(config, registry=registry)

        assert reconstructed.knowledge is kb
        assert reconstructed.search_knowledge is True

    def test_from_dict_without_registry_raises_for_knowledge(self):
        """Without a registry, an unresolvable knowledge reference fails loudly."""
        from agno.exceptions import ComponentRehydrationError

        kb = self._make_knowledge("Docs KB")
        agent = Agent(id="kb-agent", knowledge=kb)
        config = agent.to_dict()

        with pytest.raises(ComponentRehydrationError, match="Docs KB"):
            Agent.from_dict(config, registry=None, strict=True)

    def test_from_dict_without_registry_drops_knowledge_when_lenient(self):
        """strict=False preserves the old drop-and-warn behavior."""
        kb = self._make_knowledge("Docs KB")
        agent = Agent(id="kb-agent", knowledge=kb)
        config = agent.to_dict()

        reconstructed = Agent.from_dict(config, registry=None, strict=False)

        assert reconstructed.knowledge is None

    def test_from_dict_unresolved_knowledge_drops_gracefully_when_lenient(self):
        """A reference not present in the registry is dropped with strict=False."""
        kb = self._make_knowledge("Docs KB")
        agent = Agent(id="kb-agent", knowledge=kb)
        config = agent.to_dict()

        # Registry without the referenced knowledge
        reconstructed = Agent.from_dict(config, registry=Registry(), strict=False)

        assert reconstructed.knowledge is None


# =============================================================================
# save() Tests
# =============================================================================


class TestAgentSave:
    """Tests for Agent.save() method."""

    def test_save_creates_component_and_initial_config_atomically(self, basic_agent, mock_db):
        """Test first save creates the component and config together."""
        basic_agent.db = mock_db
        version = basic_agent.save()

        call_args = mock_db.create_component_with_config.call_args
        assert call_args.kwargs["component_id"] == "test-agent"
        assert call_args.kwargs["component_type"] == ComponentType.AGENT
        assert call_args.kwargs["name"] == "Test Agent"
        assert call_args.kwargs["description"] == "A test agent for unit testing"
        assert call_args.kwargs["config"]["id"] == "test-agent"
        mock_db.upsert_component.assert_not_called()
        mock_db.upsert_config.assert_not_called()
        assert version == 1

    def test_existing_save_upserts_config_with_projection(self, basic_agent, mock_db):
        """Test a published save updates config and projection together."""
        mock_db.get_component.return_value = {
            "component_id": "test-agent",
            "component_type": "agent",
            "deleted_at": None,
        }
        mock_db.upsert_config.return_value = {"version": 2}
        guard = ComponentVersionGuard(latest_version=1, current_version=1)

        basic_agent.db = mock_db
        version = basic_agent.save(guard=guard)

        mock_db.upsert_config.assert_called_once()
        call_args = mock_db.upsert_config.call_args
        assert call_args.kwargs["component_id"] == "test-agent"
        assert call_args.kwargs["guard"] == guard
        assert "config" in call_args.kwargs
        assert call_args.kwargs["projection"] == {
            "name": "Test Agent",
            "description": "A test agent for unit testing",
            "metadata": None,
        }
        assert version == 2

    def test_save_with_explicit_db(self, basic_agent, mock_db):
        """Test save uses explicitly provided db."""
        version = basic_agent.save(db=mock_db)

        mock_db.create_component_with_config.assert_called_once()
        mock_db.upsert_component.assert_not_called()
        mock_db.upsert_config.assert_not_called()
        assert version == 1

    def test_save_with_label(self, basic_agent, mock_db):
        """Test first save passes the label to the atomic create."""
        basic_agent.db = mock_db
        basic_agent.save(label="production")

        call_args = mock_db.create_component_with_config.call_args
        assert call_args.kwargs["label"] == "production"

    def test_save_with_stage(self, basic_agent, mock_db):
        """Test first save passes the stage to the atomic create."""
        basic_agent.db = mock_db
        basic_agent.save(stage="draft")

        call_args = mock_db.create_component_with_config.call_args
        assert call_args.kwargs["stage"] == "draft"

    def test_save_with_notes(self, basic_agent, mock_db):
        """Test first save passes notes to the atomic create."""
        basic_agent.db = mock_db
        basic_agent.save(notes="Initial version")

        call_args = mock_db.create_component_with_config.call_args
        assert call_args.kwargs["notes"] == "Initial version"

    def test_save_without_db_raises_error(self, basic_agent):
        """Test save raises error when no db is available."""
        with pytest.raises(ValueError, match="Db not initialized or provided"):
            basic_agent.save()

    def test_save_generates_id_from_name(self, mock_db):
        """Test save generates id from name if not provided."""
        agent = Agent(name="My Test Agent", db=mock_db)
        agent.save()

        # ID should be generated from name
        assert agent.id is not None
        call_args = mock_db.create_component_with_config.call_args
        assert call_args.kwargs["component_id"] is not None

    def test_save_handles_db_error(self, basic_agent, mock_db):
        """Test save raises error when database operation fails."""
        mock_db.create_component_with_config.side_effect = Exception("Database error")

        basic_agent.db = mock_db

        with pytest.raises(Exception, match="Database error"):
            basic_agent.save()


# =============================================================================
# load() Tests
# =============================================================================


class TestAgentLoad:
    """Tests for Agent.load() class method."""

    def test_load_returns_agent(self, mock_db, sample_agent_config):
        """Test load returns an agent from database."""
        # Remove model to avoid model lookup issues
        config = sample_agent_config.copy()
        del config["model"]
        mock_db.get_config.return_value = {"config": config}

        agent = Agent.load(id="sample-agent", db=mock_db)

        assert agent is not None
        assert agent.id == "sample-agent"
        assert agent.name == "Sample Agent"

    def test_load_with_version(self, mock_db):
        """Test load retrieves specific version."""
        mock_db.get_config.return_value = {"config": {"id": "versioned-agent", "name": "V2 Agent"}}

        Agent.load(id="versioned-agent", db=mock_db, version=2)

        mock_db.get_config.assert_called_once_with(component_id="versioned-agent", label=None, version=2)

    def test_load_with_label(self, mock_db):
        """Test load retrieves labeled version."""
        mock_db.get_config.return_value = {"config": {"id": "labeled-agent", "name": "Production Agent"}}

        Agent.load(id="labeled-agent", db=mock_db, label="production")

        mock_db.get_config.assert_called_once_with(component_id="labeled-agent", label="production", version=None)

    def test_load_with_registry(self, mock_db):
        """Test load passes registry to from_dict."""
        mock_db.get_config.return_value = {"config": {"id": "registry-agent", "tools": [{"name": "search"}]}}

        mock_registry = MagicMock()
        mock_registry.rehydrate_functions.return_value = [MagicMock()]

        agent = Agent.load(id="registry-agent", db=mock_db, registry=mock_registry)

        assert agent is not None
        mock_registry.rehydrate_functions.assert_called()

    def test_load_returns_none_when_not_found(self, mock_db):
        """Test load returns None when agent not found."""
        mock_db.get_config.return_value = None

        agent = Agent.load(id="nonexistent-agent", db=mock_db)

        assert agent is None

    def test_load_returns_none_when_config_missing(self, mock_db):
        """Test load returns None when config is missing."""
        mock_db.get_config.return_value = {"config": None}

        agent = Agent.load(id="empty-config-agent", db=mock_db)

        assert agent is None

    def test_load_sets_db_on_agent(self, mock_db):
        """Test load sets db attribute on returned agent."""
        mock_db.get_config.return_value = {"config": {"id": "db-agent", "name": "DB Agent"}}

        agent = Agent.load(id="db-agent", db=mock_db)

        assert agent is not None
        assert agent.db == mock_db

    def test_save_load_preserves_store_history_messages(self, mock_db):
        """Test that store_history_messages=True survives save/load round-trip."""
        agent = Agent(id="persist-agent", name="Persist Agent", store_history_messages=True, db=mock_db)

        # Capture the config passed to the atomic first-save operation.
        saved_config = {}

        def capture_config(**kwargs):
            saved_config.update(kwargs.get("config", {}))
            return {"component_id": "persist-agent"}, {"version": 1}

        mock_db.create_component_with_config.side_effect = capture_config
        agent.save()

        assert saved_config.get("store_history_messages") is True

        # Simulate load returning the saved config. The mock db serializes a
        # config that cannot be rebuilt standalone, so resolve it via registry.
        mock_db.get_config.return_value = {"config": saved_config}
        mock_db.id = "test-db"
        loaded = Agent.load(id="persist-agent", db=mock_db, registry=Registry(dbs=[mock_db]))

        assert loaded is not None
        assert loaded.store_history_messages is True


# =============================================================================
# delete() Tests
# =============================================================================


class TestAgentDelete:
    """Tests for Agent.delete() method."""

    def test_delete_calls_delete_component(self, basic_agent, mock_db):
        """Test delete calls delete_component."""
        mock_db.delete_component.return_value = True
        guard = ComponentVersionGuard(latest_version=1, current_version=1)

        basic_agent.db = mock_db
        result = basic_agent.delete(guard=guard)

        mock_db.delete_component.assert_called_once_with(
            component_id="test-agent",
            hard_delete=False,
            guard=guard,
            require_no_dependents=True,
            expected_component_type=ComponentType.AGENT,
        )
        assert result is True

    def test_delete_with_hard_delete(self, basic_agent, mock_db):
        """Test delete with hard_delete flag."""
        mock_db.delete_component.return_value = True
        guard = ComponentVersionGuard(latest_version=1, current_version=1)

        basic_agent.db = mock_db
        result = basic_agent.delete(hard_delete=True, guard=guard)

        mock_db.delete_component.assert_called_once_with(
            component_id="test-agent",
            hard_delete=True,
            guard=guard,
            require_no_dependents=True,
            expected_component_type=ComponentType.AGENT,
        )
        assert result is True

    def test_delete_can_explicitly_bypass_dependency_check(self, basic_agent, mock_db):
        """Test delete forwards the dangerous dependency-check escape hatch."""
        basic_agent.db = mock_db
        guard = ComponentVersionGuard(latest_version=1, current_version=1)

        assert basic_agent.delete(require_no_dependents=False, guard=guard) is True

        mock_db.delete_component.assert_called_once_with(
            component_id="test-agent",
            hard_delete=False,
            guard=guard,
            require_no_dependents=False,
            expected_component_type=ComponentType.AGENT,
        )

    def test_delete_uses_exact_catalog_v1_signature(self, basic_agent, mock_db):
        """The v2 dependency keyword must never reach a legacy override."""
        calls = []

        def legacy_delete(component_id, hard_delete=False):
            calls.append((component_id, hard_delete))
            return True

        mock_db.component_catalog_api_version = 1
        mock_db.delete_component = legacy_delete
        basic_agent.db = mock_db

        assert basic_agent.delete(require_no_dependents=False) is True
        assert calls == [("test-agent", False)]

    def test_delete_with_explicit_db(self, basic_agent, mock_db):
        """Test delete uses explicitly provided db."""
        mock_db.delete_component.return_value = True

        result = basic_agent.delete(
            db=mock_db,
            guard=ComponentVersionGuard(latest_version=1, current_version=1),
        )

        mock_db.delete_component.assert_called_once()
        assert result is True

    def test_delete_without_db_raises_error(self, basic_agent):
        """Test delete raises error when no db is available."""
        with pytest.raises(ValueError, match="Db not initialized or provided"):
            basic_agent.delete()

    def test_delete_returns_false_on_failure(self, basic_agent, mock_db):
        """Test delete returns False when operation fails."""
        mock_db.delete_component.return_value = False

        basic_agent.db = mock_db
        result = basic_agent.delete(guard=ComponentVersionGuard(latest_version=1, current_version=1))

        assert result is False


# =============================================================================
# get_agent_by_id() Tests
# =============================================================================


class TestGetAgentById:
    """Tests for get_agent_by_id() helper function."""

    def test_get_agent_by_id_returns_agent(self, mock_db):
        """Test get_agent_by_id returns agent from database."""
        mock_db.get_config.return_value = {"config": {"id": "found-agent", "name": "Found Agent"}}

        agent = get_agent_by_id(db=mock_db, id="found-agent")

        assert agent is not None
        assert agent.id == "found-agent"
        assert agent.name == "Found Agent"
        mock_db.get_config.assert_called_once_with(component_id="found-agent", label=None, version=None)

    def test_get_agent_by_id_returns_a_draft_only_component(self, tmp_path):
        """An ordinary by-id read retains the pre-2.9 draft fallback."""
        from agno.db.sqlite import SqliteDb

        db = SqliteDb(db_file=str(tmp_path / "draft-only-agent.db"))
        assert Agent(id="draft-agent", name="Draft Agent", db=db).save(stage="draft") == 1
        assert db.get_current_config("draft-agent") is None

        loaded = get_agent_by_id(db=db, id="draft-agent")

        assert loaded is not None
        assert loaded.id == "draft-agent"
        assert loaded.name == "Draft Agent"

    def test_get_agent_by_id_with_version(self, mock_db):
        """Test get_agent_by_id retrieves specific version."""
        mock_db.get_config.return_value = {"config": {"id": "versioned", "name": "V3"}}

        get_agent_by_id(db=mock_db, id="versioned", version=3)

        mock_db.get_config.assert_called_once_with(component_id="versioned", label=None, version=3)

    def test_get_agent_by_id_with_label(self, mock_db):
        """Test get_agent_by_id retrieves labeled version."""
        mock_db.get_config.return_value = {"config": {"id": "labeled", "name": "Staging"}}

        get_agent_by_id(db=mock_db, id="labeled", label="staging")

        mock_db.get_config.assert_called_once_with(component_id="labeled", label="staging", version=None)

    def test_get_agent_by_id_with_registry(self, mock_db):
        """Test get_agent_by_id passes registry."""
        mock_db.get_config.return_value = {"config": {"id": "registry-agent", "tools": [{"name": "calc"}]}}

        mock_registry = MagicMock()
        mock_registry.rehydrate_functions.return_value = [MagicMock()]

        agent = get_agent_by_id(db=mock_db, id="registry-agent", registry=mock_registry)

        assert agent is not None

    def test_get_agent_by_id_returns_none_when_not_found(self, mock_db):
        """Test get_agent_by_id returns None when not found."""
        mock_db.get_config.return_value = None

        agent = get_agent_by_id(db=mock_db, id="missing")

        assert agent is None

    def test_get_agent_by_id_sets_db(self, mock_db):
        """Test get_agent_by_id sets db on returned agent via registry."""
        # The db is set via registry lookup when config contains a serialized db reference
        mock_db.id = "test-db"
        mock_db.get_config.return_value = {
            "config": {
                "id": "db-agent",
                "name": "DB Agent",
                "db": {"type": "postgres", "id": "test-db"},
            }
        }

        # Create registry with the mock db registered
        registry = Registry(dbs=[mock_db])

        agent = get_agent_by_id(db=mock_db, id="db-agent", registry=registry)

        assert agent is not None
        assert agent.db == mock_db

    def test_get_agent_by_id_handles_error(self, mock_db):
        """Test get_agent_by_id returns None on error."""
        mock_db.get_config.side_effect = Exception("DB error")

        agent = get_agent_by_id(db=mock_db, id="error-agent")

        assert agent is None


# =============================================================================
# get_agents() Tests
# =============================================================================


class TestGetAgents:
    """Tests for get_agents() helper function."""

    def test_get_agents_returns_list(self, mock_db):
        """Test get_agents returns list of agents."""
        mock_db.list_components.return_value = (
            [
                {"component_id": "agent-1"},
                {"component_id": "agent-2"},
            ],
            None,
        )
        mock_db.get_latest_config = MagicMock(
            side_effect=[
                {"config": {"id": "agent-1", "name": "Agent 1"}},
                {"config": {"id": "agent-2", "name": "Agent 2"}},
            ]
        )

        agents = get_agents(db=mock_db)

        assert len(agents) == 2
        assert agents[0].id == "agent-1"
        assert agents[1].id == "agent-2"
        assert mock_db.get_latest_config.call_count == 2
        mock_db.get_config.assert_not_called()

    def test_get_agents_filters_by_type(self, mock_db):
        """Test get_agents filters by AGENT component type."""
        mock_db.list_components.return_value = ([], None)

        get_agents(db=mock_db)

        mock_db.list_components.assert_called_once_with(component_type=ComponentType.AGENT, exclude_component_ids=None)

    def test_get_agents_with_registry(self, mock_db):
        """Test get_agents passes registry to from_dict."""
        mock_db.list_components.return_value = (
            [{"component_id": "tools-agent"}],
            None,
        )
        mock_db.get_config.return_value = {"config": {"id": "tools-agent", "tools": [{"name": "search"}]}}

        mock_registry = MagicMock()
        mock_registry.rehydrate_functions.return_value = [MagicMock()]

        agents = get_agents(db=mock_db, registry=mock_registry)

        assert len(agents) == 1

    def test_get_agents_returns_empty_list_on_error(self, mock_db):
        """Test get_agents returns empty list on error."""
        mock_db.list_components.side_effect = Exception("DB error")

        agents = get_agents(db=mock_db)

        assert agents == []

    def test_get_agents_skips_invalid_configs(self, mock_db):
        """Test get_agents skips agents with invalid configs."""
        mock_db.list_components.return_value = (
            [
                {"component_id": "valid-agent"},
                {"component_id": "invalid-agent"},
            ],
            None,
        )
        mock_db.get_config.side_effect = [
            {"config": {"id": "valid-agent", "name": "Valid"}},
            {"config": None},  # Invalid config
        ]

        agents = get_agents(db=mock_db)

        assert len(agents) == 1
        assert agents[0].id == "valid-agent"

    def test_get_agents_sets_db_on_all_agents(self, mock_db):
        """Test get_agents sets db on all returned agents via registry."""
        # The db is set via registry lookup when config contains a serialized db reference
        mock_db.id = "test-db"
        mock_db.list_components.return_value = (
            [{"component_id": "agent-1"}],
            None,
        )
        mock_db.get_config.return_value = {
            "config": {
                "id": "agent-1",
                "name": "Agent 1",
                "db": {"type": "postgres", "id": "test-db"},
            }
        }

        # Create registry with the mock db registered
        registry = Registry(dbs=[mock_db])

        agents = get_agents(db=mock_db, registry=registry)

        assert len(agents) == 1
        assert agents[0].db == mock_db


class TestStrictToolResolution:
    def test_from_dict_external_execution_tool_loads_under_strict(self):
        """Client-executed tools never carry a server entrypoint; strict must
        not treat them as unresolved references."""
        from agno.models.openai import OpenAIChat
        from agno.tools.decorator import tool
        from agno.tools.function import Function

        @tool(external_execution=True)
        def charge_card(amount: float) -> str:
            """Charge a card."""
            return "charged"

        agent = Agent(id="ext-agent", model=OpenAIChat(id="gpt-4o-mini"), tools=[charge_card])
        config = agent.to_dict()

        rebuilt = Agent.from_dict(config, registry=Registry(), strict=True)

        names = [t.name for t in rebuilt.tools if isinstance(t, Function)]
        assert "charge_card" in names

    def test_from_dict_strict_keeps_qualified_tools_bound_to_their_toolkit(self):
        """A same-named function from a different toolkit is a different tool:
        strict refuses it, lenient warns and binds it."""
        from agno.exceptions import ComponentRehydrationError
        from agno.models.openai import OpenAIChat
        from agno.tools.function import Function
        from agno.tools.toolkit import Toolkit

        def search(query: str) -> str:
            """Search."""
            return "results"

        agent = Agent(
            id="qual-agent",
            model=OpenAIChat(id="gpt-4o-mini"),
            tools=[Toolkit(name="right_toolkit", tools=[search])],
        )
        config = agent.to_dict()
        registry = Registry(tools=[Toolkit(name="wrong_toolkit", tools=[search])])

        with pytest.raises(ComponentRehydrationError, match="right_toolkit.search"):
            Agent.from_dict(config, registry=registry, strict=True)

        lenient = Agent.from_dict(config, registry=registry, strict=False)
        bound = [t for t in lenient.tools if isinstance(t, Function) and t.name == "search"]
        assert bound and bound[0].entrypoint is not None


class TestLookupLoaderDbFallback:
    def test_get_agent_by_id_falls_back_to_caller_db(self, tmp_path):
        """An unresolvable serialized db must not leave the loaded agent with
        db=None; the caller's db is the fallback, matching Agent.load."""
        from agno.agent.agent import get_agent_by_id
        from agno.db.base import ComponentType
        from agno.db.sqlite import SqliteDb

        db = SqliteDb(db_file=str(tmp_path / "fallback.db"))
        db.upsert_component(component_id="db-agent", component_type=ComponentType.AGENT, name="A")
        db.upsert_config(
            component_id="db-agent",
            config={"id": "db-agent", "name": "A", "db": {"id": "private-db"}},
            stage="published",
        )

        agent = get_agent_by_id(db=db, id="db-agent")

        assert agent is not None
        assert agent.db is db


class TestAmbiguousKnowledge:
    def test_strict_refuses_a_knowledge_name_two_instances_claim(self):
        from agno.exceptions import ComponentRehydrationError

        class KB:
            def __init__(self, marker):
                self.name = "shared"
                self.marker = marker

        registry = Registry()
        first, second = KB("first"), KB("second")
        registry.add_knowledge(first)
        registry.add_knowledge(second)

        config = {"id": "kb-agent", "knowledge": {"name": "shared"}, "search_knowledge": True}

        with pytest.raises(ComponentRehydrationError, match="two distinct"):
            Agent.from_dict(config, registry=registry, strict=True)

        lenient = Agent.from_dict(config, registry=registry, strict=False)
        assert lenient.knowledge is first


class TestMalformedFunctionDicts:
    def test_strict_refuses_a_function_dict_that_fails_validation(self):
        from agno.exceptions import ComponentRehydrationError

        config = {
            "id": "bad-tool-agent",
            "tools": [{"name": "broken", "parameters": 5}],
        }

        with pytest.raises(ComponentRehydrationError, match="does not validate"):
            Agent.from_dict(config, registry=Registry(), strict=True)

        lenient = Agent.from_dict(config, registry=Registry(), strict=False)
        assert lenient.tools == [{"name": "broken", "parameters": 5}]


def test_strict_refuses_constructor_supplied_ambiguous_knowledge():
    """Registry(knowledge=[first, second]) never passes through add_knowledge,
    so ambiguity is computed at resolution, not trusted from the add path."""
    from agno.exceptions import ComponentRehydrationError

    class KB:
        def __init__(self, marker):
            self.name = "shared"
            self.marker = marker

    registry = Registry(knowledge=[KB("first"), KB("second")])
    config = {"id": "kb-agent", "knowledge": {"name": "shared"}, "search_knowledge": True}

    with pytest.raises(ComponentRehydrationError, match="two distinct"):
        Agent.from_dict(config, registry=registry, strict=True)


def test_strict_passes_provider_envelope_tools_through():
    """A provider-native envelope like Bedrock's {'function': {...}} carries
    itself; strict must not refuse it, with or without a registry."""
    bedrock_tool = {"function": {"name": "get_weather", "description": "W", "parameters": {"type": "object"}}}
    config = {"id": "br-agent", "tools": [bedrock_tool]}

    with_registry = Agent.from_dict(config, registry=Registry(), strict=True)
    without_registry = Agent.from_dict(config, strict=True)

    assert with_registry.tools == [bedrock_tool]
    assert without_registry.tools == [bedrock_tool]
