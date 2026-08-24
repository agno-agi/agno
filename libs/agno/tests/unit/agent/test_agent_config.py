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

from agno.agent.agent import _COMPONENT_LIST_PAGE, Agent, get_agent_by_id, get_agents
from agno.db.base import BaseDb, ComponentType
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

    # Configure common mock methods
    db.upsert_component = MagicMock()
    db.upsert_config = MagicMock(return_value={"version": 1})
    db.delete_component = MagicMock(return_value=True)
    db.get_config = MagicMock()
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

    def test_save_calls_upsert_component(self, basic_agent, mock_db):
        """Test save calls upsert_component with correct parameters."""
        mock_db.upsert_config.return_value = {"version": 1}

        basic_agent.db = mock_db
        version = basic_agent.save()

        mock_db.upsert_component.assert_called_once_with(
            component_id="test-agent",
            component_type=ComponentType.AGENT,
            name="Test Agent",
            description="A test agent for unit testing",
            metadata=None,
        )
        assert version == 1

    def test_save_calls_upsert_config(self, basic_agent, mock_db):
        """Test save calls upsert_config with agent config."""
        mock_db.upsert_config.return_value = {"version": 2}

        basic_agent.db = mock_db
        version = basic_agent.save()

        mock_db.upsert_config.assert_called_once()
        call_args = mock_db.upsert_config.call_args
        assert call_args.kwargs["component_id"] == "test-agent"
        assert "config" in call_args.kwargs
        assert version == 2

    def test_save_with_explicit_db(self, basic_agent, mock_db):
        """Test save uses explicitly provided db."""
        mock_db.upsert_config.return_value = {"version": 1}

        version = basic_agent.save(db=mock_db)

        mock_db.upsert_component.assert_called_once()
        mock_db.upsert_config.assert_called_once()
        assert version == 1

    def test_save_with_label(self, basic_agent, mock_db):
        """Test save passes label to upsert_config."""
        mock_db.upsert_config.return_value = {"version": 1}

        basic_agent.db = mock_db
        basic_agent.save(label="production")

        call_args = mock_db.upsert_config.call_args
        assert call_args.kwargs["label"] == "production"

    def test_save_with_stage(self, basic_agent, mock_db):
        """Test save passes stage to upsert_config."""
        mock_db.upsert_config.return_value = {"version": 1}

        basic_agent.db = mock_db
        basic_agent.save(stage="draft")

        call_args = mock_db.upsert_config.call_args
        assert call_args.kwargs["stage"] == "draft"

    def test_save_with_notes(self, basic_agent, mock_db):
        """Test save passes notes to upsert_config."""
        mock_db.upsert_config.return_value = {"version": 1}

        basic_agent.db = mock_db
        basic_agent.save(notes="Initial version")

        call_args = mock_db.upsert_config.call_args
        assert call_args.kwargs["notes"] == "Initial version"

    def test_save_without_db_raises_error(self, basic_agent):
        """Test save raises error when no db is available."""
        with pytest.raises(ValueError, match="Db not initialized or provided"):
            basic_agent.save()

    def test_save_generates_id_from_name(self, mock_db):
        """Test save generates id from name if not provided."""
        mock_db.upsert_config.return_value = {"version": 1}

        agent = Agent(name="My Test Agent", db=mock_db)
        agent.save()

        # ID should be generated from name
        assert agent.id is not None
        call_args = mock_db.upsert_component.call_args
        assert call_args.kwargs["component_id"] is not None

    def test_save_handles_db_error(self, basic_agent, mock_db):
        """Test save raises error when database operation fails."""
        mock_db.upsert_component.side_effect = Exception("Database error")

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

        # Capture the config passed to upsert_config during save
        saved_config = {}

        def capture_config(**kwargs):
            saved_config.update(kwargs.get("config", {}))
            return {"version": 1}

        mock_db.upsert_config.side_effect = capture_config
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

        basic_agent.db = mock_db
        result = basic_agent.delete()

        mock_db.delete_component.assert_called_once_with(
            component_id="test-agent", hard_delete=False, require_no_dependents=True
        )
        assert result is True

    def test_delete_with_hard_delete(self, basic_agent, mock_db):
        """Test delete with hard_delete flag."""
        mock_db.delete_component.return_value = True

        basic_agent.db = mock_db
        result = basic_agent.delete(hard_delete=True)

        mock_db.delete_component.assert_called_once_with(
            component_id="test-agent", hard_delete=True, require_no_dependents=True
        )
        assert result is True

    def test_delete_with_explicit_db(self, basic_agent, mock_db):
        """Test delete uses explicitly provided db."""
        mock_db.delete_component.return_value = True

        result = basic_agent.delete(db=mock_db)

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
        result = basic_agent.delete()

        assert result is False


# =============================================================================
# get_agent_by_id() Tests
# =============================================================================


class TestGetAgentById:
    """Tests for get_agent_by_id() helper function."""

    def test_get_agent_by_id_returns_agent(self, mock_db):
        """Test get_agent_by_id returns agent from database."""
        # published_only resolution reads the component row first (spec 3.3)
        mock_db.get_component = MagicMock(return_value={"component_id": "c", "current_version": 1})
        mock_db.get_config.return_value = {"config": {"id": "found-agent", "name": "Found Agent"}}

        agent = get_agent_by_id(db=mock_db, id="found-agent")

        assert agent is not None
        assert agent.id == "found-agent"
        assert agent.name == "Found Agent"

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
        # published_only resolution reads the component row first (spec 3.3)
        mock_db.get_component = MagicMock(return_value={"component_id": "c", "current_version": 1})
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
        # published_only resolution reads the component row first (spec 3.3)
        mock_db.get_component = MagicMock(return_value={"component_id": "c", "current_version": 1})
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
            2,
        )
        mock_db.get_config.side_effect = [
            {"config": {"id": "agent-1", "name": "Agent 1"}},
            {"config": {"id": "agent-2", "name": "Agent 2"}},
        ]

        agents = get_agents(db=mock_db)

        assert len(agents) == 2
        assert agents[0].id == "agent-1"
        assert agents[1].id == "agent-2"

    def test_get_agents_filters_by_type(self, mock_db):
        """Test get_agents filters by AGENT component type."""
        mock_db.list_components.return_value = ([], None)

        get_agents(db=mock_db)

        mock_db.list_components.assert_called_once_with(
            component_type=ComponentType.AGENT,
            exclude_component_ids=None,
            user_id=None,
            limit=_COMPONENT_LIST_PAGE,
            offset=0,
        )

    def test_get_agents_with_registry(self, mock_db):
        """Test get_agents passes registry to from_dict."""
        mock_db.list_components.return_value = (
            [{"component_id": "tools-agent"}],
            1,
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
            2,
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
            1,
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


# =============================================================================
# Memory manager round-trip (A3 regression: auto-generated ids 422'd dispatch)
# =============================================================================


class TestMemoryManagerRoundTrip:
    """A saved memory_manager reference must never refuse a component that
    would rebuild a perfectly good default manager on its own, and must
    round-trip a user's registered manager to the same live instance."""

    def test_auto_created_manager_survives_fresh_registry_strict_load(self):
        """enable_agentic_memory auto-creates a manager with a per-process id;
        the config must not reference it, and a fresh-process strict load (the
        dispatch shape) must succeed and rebuild the default on init."""
        from agno.agent._init import initialize_agent

        agent = Agent(id="mem-agent", name="Mem Agent", enable_agentic_memory=True)
        initialize_agent(agent)
        assert agent.memory_manager is not None
        assert agent.memory_manager.id.startswith("memory_manager_")

        config = agent.to_dict()
        assert "memory_manager" not in config

        loaded = Agent.from_dict(config, registry=Registry(), strict=True)
        assert loaded.enable_agentic_memory is True
        initialize_agent(loaded)
        assert loaded.memory_manager is not None

    def test_registered_manager_round_trips_to_same_instance(self):
        from agno.memory.manager import MemoryManager

        manager = MemoryManager(id="shared-memory")
        agent = Agent(id="mem-agent", name="Mem Agent", memory_manager=manager)

        config = agent.to_dict()
        assert config["memory_manager"] == {"registry_id": "shared-memory"}

        loaded = Agent.from_dict(config, registry=Registry(memory_managers=[manager]), strict=True)
        assert loaded.memory_manager is manager

    def test_unregistered_manager_with_memory_flags_still_raises_strict(self):
        """The flags rebuild a DEFAULT manager - the agent's own model, no
        capture instructions - which is not the manager the config named.
        Dropping the reference silently changes how memories are written,
        so strict refuses it like any other unresolvable reference."""
        from agno.exceptions import ComponentRehydrationError
        from agno.memory.manager import MemoryManager

        manager = MemoryManager(id="my-memory")
        agent = Agent(id="mem-agent", name="Mem Agent", memory_manager=manager, enable_agentic_memory=True)
        config = agent.to_dict()
        assert config["memory_manager"] == {"registry_id": "my-memory"}

        with pytest.raises(ComponentRehydrationError, match="my-memory"):
            Agent.from_dict(config, registry=Registry(), strict=True)

        # strict=False still loads the component without it.
        loaded = Agent.from_dict(config, registry=Registry(), strict=False)
        assert loaded.memory_manager is None

    def test_unregistered_manager_without_flags_raises_strict(self):
        """No flags means dropping the manager removes memory entirely; the
        user clearly asked for a specific one, so strict must refuse."""
        from agno.exceptions import ComponentRehydrationError
        from agno.memory.manager import MemoryManager

        manager = MemoryManager(id="my-memory")
        agent = Agent(id="mem-agent", name="Mem Agent", memory_manager=manager)
        config = agent.to_dict()

        with pytest.raises(ComponentRehydrationError, match="memory manager 'my-memory'"):
            Agent.from_dict(config, registry=Registry(), strict=True)

        loaded = Agent.from_dict(config, registry=Registry(), strict=False)
        assert loaded.memory_manager is None

    def test_auto_generated_id_never_serialized_even_for_explicit_manager(self):
        """An explicit manager the user never gave an id can only be
        referenced by its per-process auto id, which no fresh process can
        resolve; the reference is pure loss and must be omitted (with a
        warning when no flags would rebuild a default)."""
        from agno.memory.manager import MemoryManager

        agent = Agent(id="mem-agent", name="Mem Agent", memory_manager=MemoryManager())
        with patch("agno.agent._storage.log_warning") as mock_warn:
            config = agent.to_dict()
        assert "memory_manager" not in config
        assert mock_warn.called

    def test_legacy_auto_id_reference_dropped_under_strict(self):
        """Configs saved before ids were filtered carry auto ids that can
        never resolve; strict must drop them, not 422 the component forever."""
        config = {
            "id": "legacy-agent",
            "name": "Legacy Agent",
            "memory_manager": {"registry_id": "memory_manager_ab12cd34"},
        }

        loaded = Agent.from_dict(config, registry=Registry(), strict=True)
        assert loaded.memory_manager is None


class TestLearningReferenceRoundTrip:
    """A named LearningMachine is a registry resource: the config carries a
    reference by name and the registry supplies the live machine. An unnamed
    machine belongs to its component and inlines in full, exactly as every
    config written before machines had names."""

    def test_named_machine_serializes_as_reference_and_resolves_to_same_instance(self):
        from agno.learn import LearningMachine

        machine = LearningMachine(name="shared-brain", user_memory=True)
        agent = Agent(id="learn-agent", name="Learn Agent", learning=machine)

        config = agent.to_dict()
        assert config["learning"] == {"name": "shared-brain"}

        loaded = Agent.from_dict(config, registry=Registry(learning=[machine]), strict=True)
        assert loaded.learning is machine

    def test_unnamed_machine_still_inlines_and_rebuilds_without_a_registry(self):
        from agno.learn import LearningMachine

        agent = Agent(id="learn-agent", name="Learn Agent", learning=LearningMachine(user_memory=True))

        config = agent.to_dict()
        assert "name" not in config["learning"]
        assert config["learning"]["user_memory"] is True

        loaded = Agent.from_dict(config, registry=Registry(), strict=True)
        assert isinstance(loaded.learning, LearningMachine)
        assert loaded.learning is not agent.learning
        assert loaded.learning.name is None
        assert loaded.learning.user_memory is True

    def test_inline_shapes_are_never_mistaken_for_references(self):
        """``{}`` (a machine with every store off) and the pre-name payloads
        are inline configs: strict loads with an empty registry rebuild them."""
        from agno.learn import LearningMachine

        for payload in ({}, {"user_profile": True, "user_memory": True}, {"name": "", "user_memory": True}):
            config = {"id": "learn-agent", "name": "Learn Agent", "learning": payload}
            loaded = Agent.from_dict(config, registry=Registry(), strict=True)
            assert isinstance(loaded.learning, LearningMachine), payload

    def test_named_inline_config_rebuilds_unnamed_and_keeps_round_tripping_inline(self):
        """A dict carrying a name PLUS store keys (what LearningMachine.to_dict()
        writes for a named machine, authorable by hand) is an inline config.
        The rebuilt machine drops the name, so the next to_dict writes the
        stores again instead of a bare reference no registry resolves."""
        from agno.learn import LearningMachine

        payload = {"name": "brain", "user_memory": True, "entity_memory": True, "namespace": "west"}
        loaded = Agent.from_dict(
            {"id": "learn-agent", "name": "Learn Agent", "learning": payload}, registry=Registry(), strict=True
        )
        assert isinstance(loaded.learning, LearningMachine)
        assert loaded.learning.name is None
        assert loaded.learning.user_memory is True and loaded.learning.namespace == "west"

        resaved = loaded.to_dict()["learning"]
        assert resaved == {"user_memory": True, "entity_memory": True, "namespace": "west"}
        again = Agent.from_dict({"id": "learn-agent", "learning": resaved}, registry=Registry(), strict=True)
        assert again.learning.user_memory is True

    def test_missing_reference_raises_strict_and_drops_lenient(self):
        from agno.exceptions import ComponentRehydrationError

        config = {"id": "learn-agent", "name": "Learn Agent", "learning": {"name": "ghost"}}

        with pytest.raises(ComponentRehydrationError, match="learning machine 'ghost'"):
            Agent.from_dict(config, registry=Registry(), strict=True)
        with pytest.raises(ComponentRehydrationError, match="learning machine 'ghost'"):
            Agent.from_dict(config, registry=None, strict=True)

        with patch("agno.agent._storage.log_warning") as mock_warn:
            loaded = Agent.from_dict(config, registry=Registry(), strict=False)
        assert loaded.learning is None
        assert any("ghost" in str(call) for call in mock_warn.call_args_list)

    def test_ambiguous_name_raises_strict_and_binds_first_lenient(self):
        from agno.exceptions import ComponentRehydrationError
        from agno.learn import LearningMachine

        first = LearningMachine(name="shared-brain", user_memory=True)
        second = LearningMachine(name="shared-brain", entity_memory=True)
        registry = Registry(learning=[first, second])
        config = {"id": "learn-agent", "name": "Learn Agent", "learning": {"name": "shared-brain"}}

        with pytest.raises(ComponentRehydrationError, match="two distinct"):
            Agent.from_dict(config, registry=registry, strict=True)

        with patch("agno.agent._storage.log_warning") as mock_warn:
            loaded = Agent.from_dict(config, registry=registry, strict=False)
        assert loaded.learning is first
        assert any("more than one" in str(call) for call in mock_warn.call_args_list)

    def test_shared_machine_is_one_instance_and_the_first_binder_sets_its_model(self, tmp_path):
        """Two components referencing the same name get the SAME machine. The
        framework injects db/model into it only when unset, so the first
        component to initialize fixes them for every sharer: a registry
        machine that should capture with its own model must declare one."""
        from agno.agent._init import initialize_agent
        from agno.db.sqlite import SqliteDb
        from agno.learn import LearningMachine
        from agno.models.openai import OpenAIResponses

        db = SqliteDb(db_file=str(tmp_path / "shared.db"))
        machine = LearningMachine(name="shared-brain", user_memory=True)
        registry = Registry(learning=[machine])

        first = Agent.from_dict(
            {"id": "a1", "name": "A1", "learning": {"name": "shared-brain"}}, registry=registry, strict=True
        )
        second = Agent.from_dict(
            {"id": "a2", "name": "A2", "learning": {"name": "shared-brain"}}, registry=registry, strict=True
        )
        assert first.learning is machine and second.learning is machine

        first.db = db
        first.model = OpenAIResponses(id="gpt-5.5")
        second.db = db
        second.model = OpenAIResponses(id="gpt-5.4")
        initialize_agent(first)
        initialize_agent(second)

        assert first.learning_machine is second.learning_machine is machine
        assert machine.db is db
        assert machine.model is first.model

        # A machine that declares its own model keeps it for every sharer.
        declared = LearningMachine(name="declared", user_memory=True, model=OpenAIResponses(id="gpt-5.5"))
        third = Agent(id="a3", name="A3", db=db, model=OpenAIResponses(id="gpt-5.4"), learning=declared)
        initialize_agent(third)
        assert declared.model is not third.model
        assert declared.model.id == "gpt-5.5"


class TestMemoryManagerReferenceShapes:
    """A memory_manager reference is authored by more than to_dict: a config
    built against the registry listing carries the resource's name or id, and
    every shape has to bind the same live manager."""

    def _agent_config(self, manager_ref):
        return {"id": "mem-agent", "name": "Mem Agent", "memory_manager": manager_ref}

    def test_registry_id_key_resolves(self):
        from agno.memory.manager import MemoryManager

        manager = MemoryManager(id="mm-1", name="Support Memory")
        loaded = Agent.from_dict(
            self._agent_config({"registry_id": "mm-1"}),
            registry=Registry(memory_managers=[manager]),
            strict=True,
        )
        assert loaded.memory_manager is manager

    def test_id_key_resolves(self):
        from agno.memory.manager import MemoryManager

        manager = MemoryManager(id="mm-1", name="Support Memory")
        loaded = Agent.from_dict(
            self._agent_config({"id": "mm-1"}),
            registry=Registry(memory_managers=[manager]),
            strict=True,
        )
        assert loaded.memory_manager is manager

    def test_name_key_resolves(self):
        """The registry listing names each manager, and a config authored from
        that listing carries the name, not the id."""
        from agno.memory.manager import MemoryManager

        manager = MemoryManager(id="mm-1", name="Support Memory")
        loaded = Agent.from_dict(
            self._agent_config({"name": "Support Memory", "description": "picked in the UI"}),
            registry=Registry(memory_managers=[manager]),
            strict=True,
        )
        assert loaded.memory_manager is manager

    def test_name_key_resolves_to_id_when_manager_is_unnamed(self):
        """An unnamed manager is listed under its id, so that is the name a
        config authored from the listing carries."""
        from agno.memory.manager import MemoryManager

        manager = MemoryManager(id="mm-1")
        loaded = Agent.from_dict(
            self._agent_config({"name": "mm-1"}),
            registry=Registry(memory_managers=[manager]),
            strict=True,
        )
        assert loaded.memory_manager is manager

    def test_bare_string_reference_resolves(self):
        from agno.memory.manager import MemoryManager

        manager = MemoryManager(id="mm-1")
        loaded = Agent.from_dict(
            self._agent_config("mm-1"),
            registry=Registry(memory_managers=[manager]),
            strict=True,
        )
        assert loaded.memory_manager is manager

    def test_id_wins_over_name(self):
        """A reference that is one manager's id and another's name binds the
        manager owning the id."""
        from agno.memory.manager import MemoryManager

        by_name = MemoryManager(id="mm-1", name="shared-key")
        by_id = MemoryManager(id="shared-key", name="Other Memory")
        loaded = Agent.from_dict(
            self._agent_config({"name": "shared-key"}),
            registry=Registry(memory_managers=[by_name, by_id]),
            strict=True,
        )
        assert loaded.memory_manager is by_id

    def test_ambiguous_name_refuses_strict(self):
        from agno.exceptions import ComponentRehydrationError
        from agno.memory.manager import MemoryManager

        first = MemoryManager(id="mm-1", name="Support Memory")
        second = MemoryManager(id="mm-2", name="Support Memory")
        registry = Registry(memory_managers=[first, second])

        with pytest.raises(ComponentRehydrationError, match="two distinct"):
            Agent.from_dict(self._agent_config({"name": "Support Memory"}), registry=registry, strict=True)

        loaded = Agent.from_dict(self._agent_config({"name": "Support Memory"}), registry=registry, strict=False)
        assert loaded.memory_manager is first

    def test_unresolvable_name_still_raises_strict_and_drops_lenient(self):
        from agno.exceptions import ComponentRehydrationError
        from agno.memory.manager import MemoryManager

        registry = Registry(memory_managers=[MemoryManager(id="mm-1", name="Support Memory")])

        with pytest.raises(ComponentRehydrationError, match="memory manager 'Other Memory'"):
            Agent.from_dict(self._agent_config({"name": "Other Memory"}), registry=registry, strict=True)

        loaded = Agent.from_dict(self._agent_config({"name": "Other Memory"}), registry=registry, strict=False)
        assert loaded.memory_manager is None

    def test_keyless_reference_reports_the_payload(self):
        """A reference carrying no usable key must name what it saw, not the
        literal string 'None'."""
        from agno.exceptions import ComponentRehydrationError

        payload = {"class_path": "agno.memory.manager.MemoryManager"}

        with pytest.raises(ComponentRehydrationError) as exc_info:
            Agent.from_dict(self._agent_config(payload), registry=Registry(), strict=True)
        message = str(exc_info.value)
        assert "'None'" not in message
        assert "class_path" in message
        assert "serving" in message

        loaded = Agent.from_dict(self._agent_config(payload), registry=Registry(), strict=False)
        assert loaded.memory_manager is None

    def test_ambiguous_name_refuses_even_with_the_memory_flags_set(self):
        """An ambiguous name could bind the wrong manager, and the memory
        flags do not make that safe: what they rebuild is a default, not
        the manager the config named."""
        from agno.exceptions import ComponentRehydrationError
        from agno.memory.manager import MemoryManager

        registry = Registry(
            memory_managers=[
                MemoryManager(id="mm-1", name="Support Memory"),
                MemoryManager(id="mm-2", name="Support Memory"),
            ]
        )
        config = self._agent_config({"name": "Support Memory"})
        config["enable_agentic_memory"] = True

        with pytest.raises(ComponentRehydrationError, match="Support Memory"):
            Agent.from_dict(config, registry=registry, strict=True)

        # strict=False keeps the documented lenient behaviour: warn, and bind
        # the first of the competing managers.
        loaded = Agent.from_dict(config, registry=registry, strict=False)
        assert loaded.enable_agentic_memory is True
        assert loaded.memory_manager is not None

    def test_stale_id_key_falls_back_to_the_name_key(self):
        """The registry listing emits both an id and a name, so a config
        authored from it carries both; a manager re-registered under a new id
        must still bind through the name."""
        from agno.memory.manager import MemoryManager

        manager = MemoryManager(id="mm-new", name="Support Memory")
        loaded = Agent.from_dict(
            self._agent_config({"id": "mm-old", "name": "Support Memory"}),
            registry=Registry(memory_managers=[manager]),
            strict=True,
        )
        assert loaded.memory_manager is manager

    def test_stale_auto_generated_id_falls_back_to_the_name_key(self):
        """An auto-generated id is minted fresh every process, so the name is
        the only key that can resolve; the stale id must not swallow the
        reference and leave the component silently without memory."""
        from agno.memory.manager import MemoryManager

        manager = MemoryManager(id="mm-1", name="Support Memory")
        loaded = Agent.from_dict(
            self._agent_config({"id": "memory_manager_deadbeef", "name": "Support Memory"}),
            registry=Registry(memory_managers=[manager]),
            strict=True,
        )
        assert loaded.memory_manager is manager

    def test_auto_generated_id_with_unresolvable_name_still_raises_strict(self):
        """The auto-id escape covers a reference carrying nothing else; a real
        name alongside it is a manager the user asked for by name."""
        from agno.exceptions import ComponentRehydrationError
        from agno.memory.manager import MemoryManager

        registry = Registry(memory_managers=[MemoryManager(id="mm-1", name="Support Memory")])

        with pytest.raises(ComponentRehydrationError) as exc_info:
            Agent.from_dict(
                self._agent_config({"id": "memory_manager_deadbeef", "name": "Other Memory"}),
                registry=registry,
                strict=True,
            )
        message = str(exc_info.value)
        assert "memory_manager_deadbeef" in message
        assert "Other Memory" in message

    def test_lenient_ambiguous_name_warns_naming_the_competing_managers(self):
        """Lenient stays lenient and binds the first match, but the arbitrary
        choice must not be silent."""
        from agno.memory.manager import MemoryManager

        first = MemoryManager(id="mm-1", name="Support Memory")
        second = MemoryManager(id="mm-2", name="Support Memory")

        with patch("agno.agent._storage.log_warning") as mock_warn:
            loaded = Agent.from_dict(
                self._agent_config({"name": "Support Memory"}),
                registry=Registry(memory_managers=[first, second]),
                strict=False,
            )
        assert loaded.memory_manager is first
        warnings = " ".join(str(c) for c in mock_warn.call_args_list)
        assert "mm-1" in warnings
        assert "mm-2" in warnings


# =============================================================================
# get_agents() Pagination Tests
# =============================================================================


class TestGetAgentsPagination:
    """get_agents must page past the DB's default list_components limit.

    Published components from other users share the catalog, so without
    paging they crowd a user's own agents out of the first page.
    """

    @pytest.fixture
    def sqlite_db(self, tmp_path):
        from agno.db.sqlite import SqliteDb

        return SqliteDb(db_file=str(tmp_path / "agents_pagination.db"))

    def _create(self, db, component_id, user_id):
        db.create_component_with_config(
            component_id=component_id,
            component_type=ComponentType.AGENT,
            name=component_id,
            config={"name": component_id},
            stage="published",
            user_id=user_id,
        )

    def test_returns_all_own_agents_beyond_default_page(self, sqlite_db):
        for i in range(25):
            self._create(sqlite_db, f"own-agent-{i:02d}", "owner")

        agents = get_agents(db=sqlite_db, user_id="owner")

        assert {a.id for a in agents} == {f"own-agent-{i:02d}" for i in range(25)}

    def test_own_agents_not_crowded_out_by_foreign_published(self, sqlite_db):
        # Own rows first (older), foreign rows second (newer): the listing
        # orders created_at DESC with component_id ASC ties, so the foreign
        # rows fill the first page either way.
        for i in range(5):
            self._create(sqlite_db, f"z-own-agent-{i}", "owner")
        for i in range(25):
            self._create(sqlite_db, f"a-pub-agent-{i:02d}", "someone-else")

        agents = get_agents(db=sqlite_db, user_id="owner")

        ids = {a.id for a in agents}
        assert {f"z-own-agent-{i}" for i in range(5)} <= ids
        assert len(agents) == 30

    def test_cap_truncates_with_single_warning(self, mock_db, monkeypatch):
        import agno.agent.agent as agent_module

        monkeypatch.setattr(agent_module, "_COMPONENT_LIST_PAGE", 5)
        monkeypatch.setattr(agent_module, "_COMPONENT_LIST_CAP", 10)
        mock_warn = MagicMock()
        monkeypatch.setattr(agent_module, "log_warning", mock_warn)

        def fake_list_components(**kwargs):
            rows = [{"component_id": f"agent-{kwargs['offset'] + i:03d}"} for i in range(kwargs["limit"])]
            return rows, 50

        mock_db.list_components.side_effect = fake_list_components
        mock_db.get_config.side_effect = lambda component_id: {"config": {"name": component_id}}

        agents = get_agents(db=mock_db, user_id="owner")

        assert len(agents) == 10
        mock_warn.assert_called_once()
        assert "10 of 50" in mock_warn.call_args[0][0]

    def test_a_total_that_is_not_a_count_returns_the_page_it_read(self, mock_db):
        """BaseDb documents an int total, but nothing enforces it and the
        baseline discarded the value entirely, so an adapter that reports no
        total worked. Comparing the scan against it raises instead, and the
        caller's own error handler turns that into an EMPTY listing -- the
        silent-truncation failure the paging was added to remove."""
        mock_db.list_components.return_value = (
            [{"component_id": "agent-1"}, {"component_id": "agent-2"}],
            None,
        )
        mock_db.get_config.side_effect = lambda component_id: {"config": {"id": component_id, "name": component_id}}

        agents = get_agents(db=mock_db)

        assert [a.id for a in agents] == ["agent-1", "agent-2"]

    def test_paging_advances_the_offset_past_the_first_block(self, sqlite_db):
        # A loop stuck at offset=0 still terminates (len >= total after two
        # identical pages) but returns duplicates and misses the tail; unique
        # recovery of 120 rows requires the offset to actually advance.
        for i in range(120):
            self._create(sqlite_db, f"own-agent-{i:03d}", "owner")

        loaded = get_agents(db=sqlite_db, user_id="owner")

        assert len(loaded) == 120
        assert {item.id for item in loaded} == {f"own-agent-{i:03d}" for i in range(120)}
