"""
Unit tests for Registry class.

Tests cover:
- Registry initialization with various components
- _entrypoint_lookup property for tools
- rehydrate_function() for reconstructing Functions
- get_schema() for retrieving schemas by name
"""

import os
from typing import Optional
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from agno.registry.registry import Registry
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit

# =============================================================================
# Test Schemas
# =============================================================================


class SampleInputSchema(BaseModel):
    """Sample input schema for registry tests."""

    query: str
    limit: int = 10


class SampleOutputSchema(BaseModel):
    """Sample output schema for registry tests."""

    result: str
    count: int


class AnotherSchema(BaseModel):
    """Another test schema."""

    name: str
    value: Optional[float] = None


# =============================================================================
# Test Functions
# =============================================================================


def sample_function(x: int, y: int) -> int:
    """A sample function for testing."""
    return x + y


def another_function(text: str) -> str:
    """Another sample function."""
    return text.upper()


def search_function(query: str) -> str:
    """A search function for testing."""
    return f"Results for: {query}"


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def basic_registry():
    """Create a basic registry with no components."""
    return Registry(
        name="Basic Registry",
        description="A basic test registry",
    )


@pytest.fixture
def mock_model():
    """Create a mock model."""
    model = MagicMock()
    model.id = "gpt-4o-mini"
    return model


@pytest.fixture
def mock_db():
    """Create a mock database."""
    db = MagicMock()
    db.id = "test-db"
    return db


@pytest.fixture
def mock_vector_db():
    """Create a mock vector database."""
    vdb = MagicMock()
    vdb.id = "test-vectordb"
    return vdb


@pytest.fixture
def function_tool():
    """Create a Function tool."""
    return Function.from_callable(sample_function)


@pytest.fixture
def mock_toolkit():
    """Create a mock Toolkit with functions."""
    toolkit = MagicMock(spec=Toolkit)

    func1 = MagicMock(spec=Function)
    func1.name = "toolkit_func_1"
    func1.entrypoint = lambda: "func1 result"

    func2 = MagicMock(spec=Function)
    func2.name = "toolkit_func_2"
    func2.entrypoint = lambda: "func2 result"

    toolkit.functions = {
        "toolkit_func_1": func1,
        "toolkit_func_2": func2,
    }
    return toolkit


@pytest.fixture
def registry_with_tools(function_tool, mock_toolkit):
    """Create a registry with various tools."""
    return Registry(
        name="Tools Registry",
        tools=[function_tool, mock_toolkit, another_function],
    )


@pytest.fixture
def registry_with_schemas():
    """Create a registry with schemas."""
    return Registry(
        name="Schema Registry",
        schemas=[SampleInputSchema, SampleOutputSchema, AnotherSchema],
    )


@pytest.fixture
def full_registry(mock_model, mock_db, mock_vector_db, function_tool):
    """Create a registry with all component types."""
    return Registry(
        name="Full Registry",
        description="A registry with all components",
        tools=[function_tool, search_function],
        models=[mock_model],
        dbs=[mock_db],
        vector_dbs=[mock_vector_db],
        schemas=[SampleInputSchema, SampleOutputSchema],
    )


# =============================================================================
# Initialization Tests
# =============================================================================


class TestRegistryInit:
    """Tests for Registry initialization."""

    def test_init_basic(self, basic_registry):
        """Test basic registry initialization."""
        assert basic_registry.name == "Basic Registry"
        assert basic_registry.description == "A basic test registry"
        assert basic_registry.id is not None
        assert basic_registry.tools == []
        assert basic_registry.models == []
        assert basic_registry.dbs == []
        assert basic_registry.vector_dbs == []
        assert basic_registry.schemas == []
        assert basic_registry.functions == []

    def test_init_generates_unique_id(self):
        """Test that each registry gets a unique ID."""
        reg1 = Registry()
        reg2 = Registry()

        assert reg1.id != reg2.id

    def test_init_with_custom_id(self):
        """Test registry with custom ID."""
        reg = Registry(id="custom-id-123")

        assert reg.id == "custom-id-123"

    def test_init_with_tools(self, function_tool):
        """Test registry initialization with tools."""
        reg = Registry(tools=[function_tool, sample_function])

        assert len(reg.tools) == 2

    def test_init_with_models(self, mock_model):
        """Test registry initialization with models."""
        reg = Registry(models=[mock_model])

        assert len(reg.models) == 1
        assert reg.models[0] == mock_model

    def test_init_with_dbs(self, mock_db):
        """Test registry initialization with databases."""
        reg = Registry(dbs=[mock_db])

        assert len(reg.dbs) == 1
        assert reg.dbs[0] == mock_db

    def test_init_with_vector_dbs(self, mock_vector_db):
        """Test registry initialization with vector databases."""
        reg = Registry(vector_dbs=[mock_vector_db])

        assert len(reg.vector_dbs) == 1
        assert reg.vector_dbs[0] == mock_vector_db

    def test_init_with_schemas(self):
        """Test registry initialization with schemas."""
        reg = Registry(schemas=[SampleInputSchema, SampleOutputSchema])

        assert len(reg.schemas) == 2
        assert SampleInputSchema in reg.schemas
        assert SampleOutputSchema in reg.schemas

    def test_init_with_functions(self):
        """Test registry initialization with functions."""
        reg = Registry(functions=[sample_function, another_function])

        assert len(reg.functions) == 2
        assert sample_function in reg.functions
        assert another_function in reg.functions

    def test_init_full_registry(self, full_registry):
        """Test registry with all component types."""
        assert full_registry.name == "Full Registry"
        assert full_registry.description == "A registry with all components"
        assert len(full_registry.tools) == 2
        assert len(full_registry.models) == 1
        assert len(full_registry.dbs) == 1
        assert len(full_registry.vector_dbs) == 1
        assert len(full_registry.schemas) == 2


# =============================================================================
# _entrypoint_lookup Tests
# =============================================================================


class TestEntrypointLookup:
    """Tests for Registry._entrypoint_lookup property."""

    def test_entrypoint_lookup_with_function(self, function_tool):
        """Test entrypoint lookup with Function tool."""
        reg = Registry(tools=[function_tool])
        lookup = reg._entrypoint_lookup

        assert "sample_function" in lookup
        assert lookup["sample_function"] == function_tool.entrypoint

    def test_entrypoint_lookup_with_callable(self):
        """Test entrypoint lookup with raw callable."""
        reg = Registry(tools=[sample_function, another_function])
        lookup = reg._entrypoint_lookup

        assert "sample_function" in lookup
        assert lookup["sample_function"] == sample_function
        assert "another_function" in lookup
        assert lookup["another_function"] == another_function

    def test_entrypoint_lookup_with_toolkit(self, mock_toolkit):
        """Test entrypoint lookup with Toolkit."""
        reg = Registry(tools=[mock_toolkit])
        lookup = reg._entrypoint_lookup

        assert "toolkit_func_1" in lookup
        assert "toolkit_func_2" in lookup

    def test_entrypoint_lookup_mixed_tools(self, registry_with_tools):
        """Test entrypoint lookup with mixed tool types."""
        lookup = registry_with_tools._entrypoint_lookup

        # Function tool
        assert "sample_function" in lookup
        # Toolkit functions
        assert "toolkit_func_1" in lookup
        assert "toolkit_func_2" in lookup
        # Raw callable
        assert "another_function" in lookup

    def test_entrypoint_lookup_empty_registry(self, basic_registry):
        """Test entrypoint lookup with no tools."""
        lookup = basic_registry._entrypoint_lookup

        assert lookup == {}

    def test_entrypoint_lookup_is_cached(self, function_tool):
        """Test that entrypoint lookup is cached."""
        reg = Registry(tools=[function_tool])

        lookup1 = reg._entrypoint_lookup
        lookup2 = reg._entrypoint_lookup

        # Should return the same cached object
        assert lookup1 is lookup2


# =============================================================================
# rehydrate_function() Tests
# =============================================================================


class TestRehydrateFunction:
    """Tests for Registry.rehydrate_function() method."""

    def test_rehydrate_function_basic(self, function_tool):
        """Test basic function rehydration."""
        reg = Registry(tools=[function_tool])

        # Serialize the function
        func_dict = function_tool.to_dict()

        # Rehydrate
        rehydrated = reg.rehydrate_function(func_dict)

        assert rehydrated.name == "sample_function"
        assert rehydrated.entrypoint is not None

    def test_rehydrate_function_restores_entrypoint(self, function_tool):
        """Test that rehydration restores the entrypoint."""
        reg = Registry(tools=[function_tool])

        func_dict = function_tool.to_dict()
        rehydrated = reg.rehydrate_function(func_dict)

        # Entrypoint should be the same as original
        assert rehydrated.entrypoint == function_tool.entrypoint

    def test_rehydrate_function_from_callable(self):
        """Test rehydrating a function registered as callable."""
        reg = Registry(tools=[sample_function])

        # Create a Function from the callable and serialize it
        func = Function.from_callable(sample_function)
        func_dict = func.to_dict()

        # Rehydrate
        rehydrated = reg.rehydrate_function(func_dict)

        assert rehydrated.name == "sample_function"
        assert rehydrated.entrypoint == sample_function

    def test_rehydrate_function_not_in_registry(self, basic_registry):
        """Test rehydrating a function not in registry."""
        func = Function.from_callable(sample_function)
        func_dict = func.to_dict()

        # Rehydrate with empty registry
        rehydrated = basic_registry.rehydrate_function(func_dict)

        # Function is created but entrypoint is None
        assert rehydrated.name == "sample_function"
        assert rehydrated.entrypoint is None

    def test_rehydrate_function_preserves_metadata(self, function_tool):
        """Test that rehydration preserves function metadata."""
        reg = Registry(tools=[function_tool])

        func_dict = function_tool.to_dict()
        rehydrated = reg.rehydrate_function(func_dict)

        assert rehydrated.name == function_tool.name
        assert rehydrated.description == function_tool.description

    def test_rehydrate_multiple_functions(self):
        """Test rehydrating multiple functions."""
        reg = Registry(tools=[sample_function, another_function, search_function])

        # Rehydrate each
        funcs = [
            Function.from_callable(sample_function),
            Function.from_callable(another_function),
            Function.from_callable(search_function),
        ]

        for func in funcs:
            rehydrated = reg.rehydrate_function(func.to_dict())
            assert rehydrated.entrypoint is not None


# =============================================================================
# get_schema() Tests
# =============================================================================


class TestGetSchema:
    """Tests for Registry.get_schema() method."""

    def test_get_schema_found(self, registry_with_schemas):
        """Test getting a schema that exists."""
        schema = registry_with_schemas.get_schema("SampleInputSchema")

        assert schema is SampleInputSchema

    def test_get_schema_multiple(self, registry_with_schemas):
        """Test getting different schemas."""
        input_schema = registry_with_schemas.get_schema("SampleInputSchema")
        output_schema = registry_with_schemas.get_schema("SampleOutputSchema")
        another = registry_with_schemas.get_schema("AnotherSchema")

        assert input_schema is SampleInputSchema
        assert output_schema is SampleOutputSchema
        assert another is AnotherSchema

    def test_get_schema_not_found(self, registry_with_schemas):
        """Test getting a schema that doesn't exist."""
        schema = registry_with_schemas.get_schema("NonExistentSchema")

        assert schema is None

    def test_get_schema_empty_registry(self, basic_registry):
        """Test getting schema from empty registry."""
        schema = basic_registry.get_schema("SampleInputSchema")

        assert schema is None

    def test_get_schema_case_sensitive(self, registry_with_schemas):
        """Test that schema lookup is case sensitive."""
        # Correct case
        found = registry_with_schemas.get_schema("SampleInputSchema")
        assert found is SampleInputSchema

        # Wrong case
        not_found = registry_with_schemas.get_schema("testinputschema")
        assert not_found is None

        not_found2 = registry_with_schemas.get_schema("TESTINPUTSCHEMA")
        assert not_found2 is None


# =============================================================================
# Integration Tests
# =============================================================================


class TestRegistryIntegration:
    """Integration tests for Registry with Agent/Team/Workflow."""

    def test_registry_with_agent_from_dict(self, full_registry):
        """Test using registry with Agent.from_dict."""
        from agno.agent.agent import Agent

        # Create agent config with tools - include parameters to match Function requirements
        config = {
            "id": "test-agent",
            "name": "Test Agent",
            "tools": [
                {
                    "name": "sample_function",
                    "description": "A sample function",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "integer"},
                            "y": {"type": "integer"},
                        },
                    },
                }
            ],
        }

        # Create agent using registry
        agent = Agent.from_dict(config, registry=full_registry)

        assert agent.id == "test-agent"
        # Tools should be rehydrated
        if agent.tools:
            assert len(agent.tools) == 1

    def test_registry_preserves_model_connection_params(self):
        """Reconstructing an agent reuses the registered model instance, keeping connection params.

        The registry holds the live, fully-configured instance (with credentials and client state),
        so from_dict should prefer it over a rebuild. See Registry.get_model.
        """
        from agno.agent.agent import Agent
        from agno.models.azure import AzureOpenAI

        model = AzureOpenAI(
            id="gpt-4.1-mini",
            api_version="2024-12-01-preview",
            azure_endpoint="https://example.cognitiveservices.azure.com",
        )
        registry = Registry(models=[model])

        config = {
            "id": "test-agent",
            "name": "Test Agent",
            "model": model.to_dict(),
        }
        # Non-secret connection params now round-trip through to_dict ...
        assert config["model"]["azure_endpoint"] == "https://example.cognitiveservices.azure.com"
        assert "api_key" not in config["model"]  # ... but credentials never do.

        agent = Agent.from_dict(config, registry=registry)

        # The live, fully-configured instance is reused -- not a bare rebuild.
        assert agent.model is model
        assert agent.model.azure_endpoint == "https://example.cognitiveservices.azure.com"
        assert agent.model.api_version == "2024-12-01-preview"

    def test_from_dict_without_registry_recovers_connection_params(self):
        """Without a registry, the model is rebuilt from its dict and now recovers non-secret params.

        This is the self-healing fallback: even an agent that was never registered keeps its endpoint
        because to_dict serializes it. Only credentials must come from env/registry.
        """
        from agno.agent.agent import Agent
        from agno.models.azure import AzureOpenAI

        config = {
            "id": "test-agent",
            "name": "Test Agent",
            "model": {
                "id": "gpt-4.1-mini",
                "name": "AzureOpenAI",
                "provider": "Azure",
                "azure_endpoint": "https://example.cognitiveservices.azure.com",
                "api_version": "2024-12-01-preview",
            },
        }

        agent = Agent.from_dict(config)

        assert isinstance(agent.model, AzureOpenAI)
        assert agent.model.id == "gpt-4.1-mini"
        assert agent.model.azure_endpoint == "https://example.cognitiveservices.azure.com"
        assert agent.model.api_version == "2024-12-01-preview"

    def test_registry_schema_with_agent(self):
        """Test registry schema lookup with agent config."""
        reg = Registry(schemas=[SampleInputSchema, SampleOutputSchema])

        # Simulate what from_dict does for schemas
        schema_name = "SampleInputSchema"
        schema = reg.get_schema(schema_name)

        assert schema is SampleInputSchema
        assert issubclass(schema, BaseModel)

    def test_empty_registry_handles_gracefully(self):
        """Test that empty registry handles operations gracefully."""
        reg = Registry()

        # Should not raise errors
        lookup = reg._entrypoint_lookup
        assert lookup == {}

        schema = reg.get_schema("SomeSchema")
        assert schema is None

        # Rehydrate with no matching entrypoint - need valid parameters
        func_dict = {
            "name": "unknown_func",
            "description": "Unknown",
            "parameters": {"type": "object", "properties": {}},
        }
        rehydrated = reg.rehydrate_function(func_dict)
        assert rehydrated.entrypoint is None


# =============================================================================
# get_function() Tests
# =============================================================================


class TestGetFunction:
    """Tests for Registry.get_function() method."""

    def test_get_function_found(self):
        """Test getting a function that exists."""
        reg = Registry(functions=[sample_function, another_function])

        func = reg.get_function("sample_function")

        assert func is sample_function

    def test_get_function_multiple(self):
        """Test getting different functions."""
        reg = Registry(functions=[sample_function, another_function, search_function])

        func1 = reg.get_function("sample_function")
        func2 = reg.get_function("another_function")
        func3 = reg.get_function("search_function")

        assert func1 is sample_function
        assert func2 is another_function
        assert func3 is search_function

    def test_get_function_not_found(self):
        """Test getting a function that doesn't exist."""
        reg = Registry(functions=[sample_function])

        func = reg.get_function("nonexistent_function")

        assert func is None

    def test_get_function_empty_registry(self, basic_registry):
        """Test getting function from empty registry."""
        func = basic_registry.get_function("sample_function")

        assert func is None

    def test_get_function_case_sensitive(self):
        """Test that function lookup is case sensitive."""
        reg = Registry(functions=[sample_function])

        # Correct name
        found = reg.get_function("sample_function")
        assert found is sample_function

        # Wrong case
        not_found = reg.get_function("Sample_Function")
        assert not_found is None

        not_found2 = reg.get_function("SAMPLE_FUNCTION")
        assert not_found2 is None

    def test_get_function_with_lambda(self):
        """Test that lambdas work (they have __name__ = '<lambda>')."""
        my_lambda = lambda x: x * 2  # noqa: E731
        reg = Registry(functions=[my_lambda])

        # Lambda functions have __name__ = '<lambda>'
        func = reg.get_function("<lambda>")

        assert func is my_lambda


# =============================================================================
# get_db() Tests
# =============================================================================


class TestGetDb:
    """Tests for Registry.get_db() method."""

    def test_get_db_found(self, mock_db):
        """Test getting a database that exists."""
        reg = Registry(dbs=[mock_db])

        db = reg.get_db("test-db")

        assert db is mock_db

    def test_get_db_multiple(self):
        """Test getting different databases."""
        db1 = MagicMock()
        db1.id = "db-1"
        db2 = MagicMock()
        db2.id = "db-2"
        db3 = MagicMock()
        db3.id = "db-3"

        reg = Registry(dbs=[db1, db2, db3])

        assert reg.get_db("db-1") is db1
        assert reg.get_db("db-2") is db2
        assert reg.get_db("db-3") is db3

    def test_get_db_not_found(self, mock_db):
        """Test getting a database that doesn't exist."""
        reg = Registry(dbs=[mock_db])

        db = reg.get_db("nonexistent-db")

        assert db is None

    def test_get_db_empty_registry(self, basic_registry):
        """Test getting database from empty registry."""
        db = basic_registry.get_db("some-db")

        assert db is None

    def test_get_db_case_sensitive(self, mock_db):
        """Test that database lookup is case sensitive."""
        reg = Registry(dbs=[mock_db])

        # Correct id
        found = reg.get_db("test-db")
        assert found is mock_db

        # Wrong case
        not_found = reg.get_db("Test-Db")
        assert not_found is None

        not_found2 = reg.get_db("TEST-DB")
        assert not_found2 is None


# =============================================================================
# get_model() Tests
# =============================================================================


class TestGetModel:
    """Tests for Registry.get_model() method."""

    def _model(self, id, provider, name):
        m = MagicMock()
        m.id = id
        m.provider = provider
        m.name = name
        return m

    def test_get_model_found_by_id(self):
        """A single registered model is returned by id alone."""
        model = self._model("gpt-4.1-mini", "Azure", "AzureOpenAI")
        reg = Registry(models=[model])

        assert reg.get_model("gpt-4.1-mini") is model

    def test_get_model_not_found(self):
        """An unknown id returns None so the caller can fall back to dict reconstruction."""
        reg = Registry(models=[self._model("gpt-4.1-mini", "Azure", "AzureOpenAI")])

        assert reg.get_model("does-not-exist") is None

    def test_get_model_empty_registry(self, basic_registry):
        """An empty registry returns None."""
        assert basic_registry.get_model("gpt-4.1-mini") is None

    def test_get_model_disambiguates_by_provider_and_name(self):
        """Models sharing an id are disambiguated by provider/name (e.g. OpenAIChat vs Responses)."""
        chat = self._model("gpt-5.5", "OpenAI", "OpenAIChat")
        responses = self._model("gpt-5.5", "OpenAI", "OpenAIResponses")
        reg = Registry(models=[chat, responses])

        assert reg.get_model("gpt-5.5", provider="OpenAI", name="OpenAIChat") is chat
        assert reg.get_model("gpt-5.5", provider="OpenAI", name="OpenAIResponses") is responses

    def test_get_model_no_match_on_provider_returns_none(self):
        """When provider is given and no registered model matches, None is returned."""
        model = self._model("gpt-4.1-mini", "Azure", "AzureOpenAI")
        reg = Registry(models=[model])

        assert reg.get_model("gpt-4.1-mini", provider="OpenAI") is None

    def test_get_model_empty_id(self):
        """A falsy id returns None."""
        reg = Registry(models=[self._model("gpt-4.1-mini", "Azure", "AzureOpenAI")])

        assert reg.get_model("") is None

    def test_get_model_disambiguates_by_connection_params(self):
        """Two deployments of the same model at different endpoints resolve by connection params."""
        pytest.importorskip("openai")
        os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")
        from agno.models.azure import AzureOpenAI

        endpoint_a = "https://a.cognitiveservices.azure.com"
        endpoint_b = "https://b.cognitiveservices.azure.com"
        model_a = AzureOpenAI(id="gpt-4.1-mini", azure_endpoint=endpoint_a)
        model_b = AzureOpenAI(id="gpt-4.1-mini", azure_endpoint=endpoint_b)
        reg = Registry(models=[model_a, model_b])

        resolved = reg.get_model(
            "gpt-4.1-mini", provider="Azure", name="AzureOpenAI", params={"azure_endpoint": endpoint_b}
        )
        assert resolved is model_b

    def test_get_model_declines_ambiguous_match(self, monkeypatch):
        """When candidates can't be told apart, decline (return None) rather than guess an endpoint."""
        pytest.importorskip("openai")
        os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")
        import agno.registry.registry as registry_module
        from agno.models.azure import AzureOpenAI

        warnings = []
        monkeypatch.setattr(registry_module, "log_warning", lambda msg, *a, **k: warnings.append(msg))

        reg = Registry(
            models=[
                AzureOpenAI(id="gpt-4.1-mini", azure_endpoint="https://a.cognitiveservices.azure.com"),
                AzureOpenAI(id="gpt-4.1-mini", azure_endpoint="https://b.cognitiveservices.azure.com"),
            ]
        )

        # No connection params to disambiguate the two registered deployments.
        assert reg.get_model("gpt-4.1-mini", provider="Azure", name="AzureOpenAI") is None
        assert warnings and "gpt-4.1-mini" in warnings[0]


# =============================================================================
# get_agent() / get_team() Tests
# =============================================================================


class TestGetAgent:
    """Tests for Registry.get_agent() method."""

    def test_get_agent_found(self):
        """Test getting an agent that exists."""
        agent = MagicMock()
        agent.id = "agent-1"
        reg = Registry(agents=[agent])

        result = reg.get_agent("agent-1")

        assert result is agent

    def test_get_agent_multiple(self):
        """Test getting different agents."""
        a1 = MagicMock()
        a1.id = "a1"
        a2 = MagicMock()
        a2.id = "a2"
        reg = Registry(agents=[a1, a2])

        assert reg.get_agent("a1") is a1
        assert reg.get_agent("a2") is a2

    def test_get_agent_not_found(self):
        """Test getting an agent that doesn't exist."""
        agent = MagicMock()
        agent.id = "agent-1"
        reg = Registry(agents=[agent])

        assert reg.get_agent("nonexistent") is None

    def test_get_agent_empty_registry(self, basic_registry):
        """Test getting agent from registry with no agents."""
        assert basic_registry.get_agent("any-id") is None

    def test_get_agent_no_id_attribute(self):
        """Test agent without id attribute is skipped."""
        agent = MagicMock(spec=[])  # no attributes
        reg = Registry(agents=[agent])

        assert reg.get_agent("anything") is None


class TestGetTeam:
    """Tests for Registry.get_team() method."""

    def test_get_team_found(self):
        """Test getting a team that exists."""
        team = MagicMock()
        team.id = "team-1"
        reg = Registry(teams=[team])

        result = reg.get_team("team-1")

        assert result is team

    def test_get_team_not_found(self):
        """Test getting a team that doesn't exist."""
        team = MagicMock()
        team.id = "team-1"
        reg = Registry(teams=[team])

        assert reg.get_team("nonexistent") is None

    def test_get_team_empty_registry(self, basic_registry):
        """Test getting team from registry with no teams."""
        assert basic_registry.get_team("any-id") is None


# =============================================================================
# get_agent_ids() / get_team_ids() / get_all_component_ids() Tests
# =============================================================================


class TestGetComponentIds:
    """Tests for Registry ID set methods."""

    def test_get_agent_ids(self):
        """Test getting all agent IDs."""
        a1 = MagicMock()
        a1.id = "agent-1"
        a2 = MagicMock()
        a2.id = "agent-2"
        reg = Registry(agents=[a1, a2])

        assert reg.get_agent_ids() == {"agent-1", "agent-2"}

    def test_get_agent_ids_empty(self, basic_registry):
        """Test agent IDs from empty registry."""
        assert basic_registry.get_agent_ids() == set()

    def test_get_agent_ids_skips_none(self):
        """Test that agents without id are excluded."""
        a1 = MagicMock()
        a1.id = "agent-1"
        a2 = MagicMock(spec=[])  # no id attribute
        reg = Registry(agents=[a1, a2])

        assert reg.get_agent_ids() == {"agent-1"}

    def test_get_team_ids(self):
        """Test getting all team IDs."""
        t1 = MagicMock()
        t1.id = "team-1"
        t2 = MagicMock()
        t2.id = "team-2"
        reg = Registry(teams=[t1, t2])

        assert reg.get_team_ids() == {"team-1", "team-2"}

    def test_get_team_ids_empty(self, basic_registry):
        """Test team IDs from empty registry."""
        assert basic_registry.get_team_ids() == set()

    def test_get_all_component_ids(self):
        """Test getting combined agent + team IDs."""
        a1 = MagicMock()
        a1.id = "agent-1"
        t1 = MagicMock()
        t1.id = "team-1"
        reg = Registry(agents=[a1], teams=[t1])

        assert reg.get_all_component_ids() == {"agent-1", "team-1"}

    def test_get_all_component_ids_no_overlap(self):
        """Test that agent and team IDs are unioned, not intersected."""
        a1 = MagicMock()
        a1.id = "shared-id"
        t1 = MagicMock()
        t1.id = "shared-id"
        reg = Registry(agents=[a1], teams=[t1])

        # Same ID from both should appear once
        assert reg.get_all_component_ids() == {"shared-id"}

    def test_get_all_component_ids_empty(self, basic_registry):
        """Test combined IDs from empty registry."""
        assert basic_registry.get_all_component_ids() == set()


# =============================================================================
# get_knowledge() / get_knowledge_names() Tests
# =============================================================================


class TestGetKnowledge:
    """Tests for Registry.get_knowledge() and get_knowledge_names()."""

    def test_init_with_knowledge(self):
        """Test registry initialization with knowledge instances."""
        kb = MagicMock()
        kb.name = "Docs KB"
        reg = Registry(knowledge=[kb])

        assert len(reg.knowledge) == 1
        assert reg.knowledge[0] is kb

    def test_get_knowledge_found(self):
        """Test getting a knowledge instance that exists by name."""
        kb = MagicMock()
        kb.name = "Docs KB"
        reg = Registry(knowledge=[kb])

        assert reg.get_knowledge("Docs KB") is kb

    def test_get_knowledge_multiple(self):
        """Test getting different knowledge instances."""
        kb1 = MagicMock()
        kb1.name = "KB One"
        kb2 = MagicMock()
        kb2.name = "KB Two"
        reg = Registry(knowledge=[kb1, kb2])

        assert reg.get_knowledge("KB One") is kb1
        assert reg.get_knowledge("KB Two") is kb2

    def test_get_knowledge_not_found(self):
        """Test getting a knowledge instance that doesn't exist."""
        kb = MagicMock()
        kb.name = "Docs KB"
        reg = Registry(knowledge=[kb])

        assert reg.get_knowledge("Nonexistent") is None

    def test_get_knowledge_empty_registry(self, basic_registry):
        """Test getting knowledge from registry with no knowledge."""
        assert basic_registry.get_knowledge("any") is None

    def test_get_knowledge_names(self):
        """Test getting all knowledge names."""
        kb1 = MagicMock()
        kb1.name = "KB One"
        kb2 = MagicMock()
        kb2.name = "KB Two"
        reg = Registry(knowledge=[kb1, kb2])

        assert reg.get_knowledge_names() == {"KB One", "KB Two"}

    def test_get_knowledge_names_empty(self, basic_registry):
        """Test knowledge names from empty registry."""
        assert basic_registry.get_knowledge_names() == set()

    def test_get_knowledge_names_skips_none(self):
        """Test that knowledge instances without a name are excluded."""
        kb1 = MagicMock()
        kb1.name = "KB One"
        kb2 = MagicMock()
        kb2.name = None
        reg = Registry(knowledge=[kb1, kb2])

        assert reg.get_knowledge_names() == {"KB One"}


# =============================================================================
# get_memory_manager() / get_session_summary_manager() Tests
# =============================================================================


class TestGetMemoryManager:
    """Tests for Registry memory manager methods."""

    def test_init_with_memory_managers(self):
        """Test registry initialization with memory managers."""
        mm = MagicMock()
        mm.id = "mm-1"
        reg = Registry(memory_managers=[mm])

        assert len(reg.memory_managers) == 1
        assert reg.memory_managers[0] is mm

    def test_get_memory_manager_found(self):
        """Test getting a memory manager that exists by id."""
        mm = MagicMock()
        mm.id = "mm-1"
        reg = Registry(memory_managers=[mm])

        assert reg.get_memory_manager("mm-1") is mm

    def test_get_memory_manager_not_found(self):
        """Test getting a memory manager that doesn't exist."""
        mm = MagicMock()
        mm.id = "mm-1"
        reg = Registry(memory_managers=[mm])

        assert reg.get_memory_manager("nonexistent") is None

    def test_get_memory_manager_empty_registry(self, basic_registry):
        """Test getting memory manager from empty registry."""
        assert basic_registry.get_memory_manager("any") is None

    def test_get_memory_manager_ids(self):
        """Test getting all memory manager ids."""
        mm1 = MagicMock()
        mm1.id = "mm-1"
        mm2 = MagicMock()
        mm2.id = "mm-2"
        reg = Registry(memory_managers=[mm1, mm2])

        assert reg.get_memory_manager_ids() == {"mm-1", "mm-2"}

    def test_get_memory_manager_ids_empty(self, basic_registry):
        """Test memory manager ids from empty registry."""
        assert basic_registry.get_memory_manager_ids() == set()

    def test_get_memory_manager_ids_skips_none(self):
        """Test that memory managers without an id are excluded."""
        mm1 = MagicMock()
        mm1.id = "mm-1"
        mm2 = MagicMock()
        mm2.id = None
        reg = Registry(memory_managers=[mm1, mm2])

        assert reg.get_memory_manager_ids() == {"mm-1"}


class TestGetSessionSummaryManager:
    """Tests for Registry session summary manager methods."""

    def test_init_with_session_summary_managers(self):
        """Test registry initialization with session summary managers."""
        sm = MagicMock()
        sm.id = "sm-1"
        reg = Registry(session_summary_managers=[sm])

        assert len(reg.session_summary_managers) == 1
        assert reg.session_summary_managers[0] is sm

    def test_get_session_summary_manager_found(self):
        """Test getting a session summary manager that exists by id."""
        sm = MagicMock()
        sm.id = "sm-1"
        reg = Registry(session_summary_managers=[sm])

        assert reg.get_session_summary_manager("sm-1") is sm

    def test_get_session_summary_manager_not_found(self):
        """Test getting a session summary manager that doesn't exist."""
        sm = MagicMock()
        sm.id = "sm-1"
        reg = Registry(session_summary_managers=[sm])

        assert reg.get_session_summary_manager("nonexistent") is None

    def test_get_session_summary_manager_empty_registry(self, basic_registry):
        """Test getting session summary manager from empty registry."""
        assert basic_registry.get_session_summary_manager("any") is None

    def test_get_session_summary_manager_ids(self):
        """Test getting all session summary manager ids."""
        sm1 = MagicMock()
        sm1.id = "sm-1"
        sm2 = MagicMock()
        sm2.id = "sm-2"
        reg = Registry(session_summary_managers=[sm1, sm2])

        assert reg.get_session_summary_manager_ids() == {"sm-1", "sm-2"}

    def test_get_session_summary_manager_ids_empty(self, basic_registry):
        """Test session summary manager ids from empty registry."""
        assert basic_registry.get_session_summary_manager_ids() == set()


# =============================================================================
# add_* methods (dedup + cache invalidation)
# =============================================================================


def _model(model_id, provider="openai"):
    """Build a lightweight model-like object for add_model tests."""
    m = MagicMock()
    m.id = model_id
    m.provider = provider
    # Make isinstance(m, Model) pass
    from agno.models.base import Model

    m.__class__ = type("MockModel", (Model,), {})
    return m


class TestAddModel:
    """Tests for Registry.add_model()."""

    def test_adds_model(self):
        reg = Registry()
        reg.add_model(_model("gpt-5.4"))
        assert [(m.provider, m.id) for m in reg.models] == [("openai", "gpt-5.4")]

    def test_dedupes_same_provider_and_id(self):
        reg = Registry()
        reg.add_model(_model("gpt-5.4"))
        reg.add_model(_model("gpt-5.4"))  # distinct object, same provider+id
        assert len(reg.models) == 1

    def test_keeps_same_id_different_provider(self):
        reg = Registry()
        reg.add_model(_model("m", provider="openai"))
        reg.add_model(_model("m", provider="azure"))
        assert len(reg.models) == 2

    def test_keeps_distinct_classes_sharing_provider_and_id(self):
        """Different classes that report the same provider string and id are not collapsed.

        OpenAIChat and OpenAIResponses both report provider "OpenAI" but are genuinely different
        integrations (Chat Completions vs Responses API); the three Azure model classes likewise
        all report provider "Azure".
        """
        pytest.importorskip("openai")  # openai is an optional extra, not a base dependency
        os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")
        from agno.models.openai.chat import OpenAIChat
        from agno.models.openai.responses import OpenAIResponses

        reg = Registry()
        reg.add_model(OpenAIChat(id="gpt-5.4"))
        reg.add_model(OpenAIResponses(id="gpt-5.4"))
        assert len(reg.models) == 2
        assert {type(m).__name__ for m in reg.models} == {"OpenAIChat", "OpenAIResponses"}
        # Both report the same display provider, confirming the class is what disambiguates.
        assert {m.provider for m in reg.models} == {"OpenAI"}

    def test_dedupes_same_class_provider_and_id(self):
        pytest.importorskip("openai")  # openai is an optional extra, not a base dependency
        os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")
        from agno.models.openai.responses import OpenAIResponses

        reg = Registry()
        reg.add_model(OpenAIResponses(id="gpt-5.4"))
        reg.add_model(OpenAIResponses(id="gpt-5.4"))  # genuine duplicate
        assert len(reg.models) == 1

    def test_keeps_same_class_id_different_endpoint(self):
        """Same class and id but different endpoints are kept distinct, not collapsed.

        Otherwise a second Azure deployment of the same model would be silently dropped and requests
        routed to the first one's endpoint. See _model_identity.
        """
        pytest.importorskip("openai")
        os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")
        from agno.models.azure import AzureOpenAI

        reg = Registry()
        reg.add_model(AzureOpenAI(id="gpt-4.1-mini", azure_endpoint="https://a.cognitiveservices.azure.com"))
        reg.add_model(AzureOpenAI(id="gpt-4.1-mini", azure_endpoint="https://b.cognitiveservices.azure.com"))
        assert len(reg.models) == 2
        assert {m.azure_endpoint for m in reg.models} == {
            "https://a.cognitiveservices.azure.com",
            "https://b.cognitiveservices.azure.com",
        }

    def test_dedupes_same_class_id_and_endpoint(self):
        """Same class, id and endpoint collapse as before -- they are interchangeable."""
        pytest.importorskip("openai")
        os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")
        from agno.models.azure import AzureOpenAI

        reg = Registry()
        reg.add_model(AzureOpenAI(id="gpt-4.1-mini", azure_endpoint="https://a.cognitiveservices.azure.com"))
        reg.add_model(AzureOpenAI(id="gpt-4.1-mini", azure_endpoint="https://a.cognitiveservices.azure.com"))
        assert len(reg.models) == 1

    def test_logs_debug_when_dropping_matching_model(self, monkeypatch):
        # A re-instantiated model (catalog id reused) is benign, so the skip is
        # logged at debug rather than warned.
        import agno.registry.registry as registry_module

        debugs = []
        monkeypatch.setattr(registry_module, "log_debug", lambda msg, *a, **k: debugs.append(msg))

        m1 = _model("gpt-5.4")
        m2 = _model("gpt-5.4")  # same provider+id, distinct instance
        reg = Registry()
        reg.add_model(m1)
        reg.add_model(m2)
        assert len(reg.models) == 1 and reg.models[0] is m1
        assert debugs and "gpt-5.4" in debugs[0]

    def test_no_log_when_same_model_instance_repeats(self, monkeypatch):
        import agno.registry.registry as registry_module

        logs = []
        monkeypatch.setattr(registry_module, "log_warning", lambda msg, *a, **k: logs.append(msg))
        monkeypatch.setattr(registry_module, "log_debug", lambda msg, *a, **k: logs.append(msg))

        m = _model("gpt-5.4")
        reg = Registry()
        reg.add_model(m)
        reg.add_model(m)
        assert len(reg.models) == 1 and logs == []

    def test_ignores_non_model(self):
        reg = Registry()
        reg.add_model("openai:gpt-5.4")
        reg.add_model(None)
        assert reg.models == []


class TestAddTool:
    """Tests for Registry.add_tool()."""

    def test_adds_tool(self):
        reg = Registry()

        def my_tool():
            pass

        reg.add_tool(my_tool)
        assert reg.tools == [my_tool]

    def test_dedupes_same_object(self):
        reg = Registry()
        tk = Toolkit(name="tk", tools=[])
        reg.add_tool(tk)
        reg.add_tool(tk)
        assert reg.tools.count(tk) == 1

    def test_dedupes_toolkit_with_matching_structural_key(self):
        # Two distinct instances of the same toolkit (same type, name, function
        # set) collapse to one; the first (user-declared) instance wins.
        reg = Registry()
        tk1 = Toolkit(name="same", tools=[])
        tk2 = Toolkit(name="same", tools=[])
        reg.add_tool(tk1)
        reg.add_tool(tk2)
        assert reg.tools == [tk1]

    def test_logs_debug_when_dropping_matching_toolkit(self, monkeypatch):
        # Re-instantiating a default toolkit in two places is common and benign,
        # so the skip is logged at debug rather than warned.
        import agno.registry.registry as registry_module

        debugs = []
        monkeypatch.setattr(registry_module, "log_debug", lambda msg, *a, **k: debugs.append(msg))

        reg = Registry()
        reg.add_tool(Toolkit(name="same", tools=[]))
        reg.add_tool(Toolkit(name="same", tools=[]))
        assert debugs and "same" in debugs[0]

    def test_keeps_toolkits_with_different_function_sets(self):
        # Same type and name but different functions are genuinely different
        # tools (e.g. configured via include_tools/exclude_tools) and are kept.
        def alpha():
            pass

        def beta():
            pass

        reg = Registry()
        tk1 = Toolkit(name="same", tools=[alpha])
        tk2 = Toolkit(name="same", tools=[beta])
        reg.add_tool(tk1)
        reg.add_tool(tk2)
        assert tk1 in reg.tools and tk2 in reg.tools

    def test_keeps_distinct_toolkit_subclasses_sharing_a_name(self):
        class ToolkitA(Toolkit):
            pass

        class ToolkitB(Toolkit):
            pass

        reg = Registry()
        tk1 = ToolkitA(name="same", tools=[])
        tk2 = ToolkitB(name="same", tools=[])
        reg.add_tool(tk1)
        reg.add_tool(tk2)
        assert tk1 in reg.tools and tk2 in reg.tools

    def test_dedupes_bound_method_by_equality(self):
        # A bound method builds a fresh object on each access, so identity dedup
        # misses it; equality dedup (same __self__/__func__) catches it.
        class Helper:
            def lookup(self):
                pass

        helper = Helper()
        reg = Registry()
        reg.add_tool(helper.lookup)
        reg.add_tool(helper.lookup)
        assert len(reg.tools) == 1

    def test_keeps_distinct_lambdas_sharing_a_name(self):
        # Lambdas have no value equality, so == falls back to identity and both
        # are kept despite sharing the name "<lambda>".
        reg = Registry()
        a = lambda: 1  # noqa: E731
        b = lambda: 2  # noqa: E731
        reg.add_tool(a)
        reg.add_tool(b)
        assert a in reg.tools and b in reg.tools

    def test_invalidates_entrypoint_lookup_cache(self):
        reg = Registry()

        def tool_a():
            pass

        reg.add_tool(tool_a)
        # Prime the cached property
        assert "tool_a" in reg._entrypoint_lookup

        def tool_b():
            pass

        reg.add_tool(tool_b)
        # Cache must have been invalidated and rebuilt with tool_b
        assert "tool_b" in reg._entrypoint_lookup


class TestAddDbAndVectorDb:
    """Tests for Registry.add_db() and add_vector_db()."""

    def test_add_db_dedupes_by_id(self):
        from agno.db.base import BaseDb

        db1 = MagicMock(spec=BaseDb)
        db1.id = "db-1"
        db2 = MagicMock(spec=BaseDb)
        db2.id = "db-1"  # same id, distinct instance
        reg = Registry()
        reg.add_db(db1)
        reg.add_db(db2)
        assert len(reg.dbs) == 1

    def test_add_db_warns_when_dropping_matching_id(self, monkeypatch):
        import agno.registry.registry as registry_module
        from agno.db.base import BaseDb

        warnings = []
        monkeypatch.setattr(registry_module, "log_warning", lambda msg, *a, **k: warnings.append(msg))

        db1 = MagicMock(spec=BaseDb)
        db1.id = "db-1"
        db2 = MagicMock(spec=BaseDb)
        db2.id = "db-1"  # same id, distinct instance
        reg = Registry()
        reg.add_db(db1)
        reg.add_db(db2)
        assert len(reg.dbs) == 1 and reg.dbs[0] is db1
        assert warnings and "db-1" in warnings[0]

    def test_add_db_no_warning_when_same_instance_repeats(self, monkeypatch):
        import agno.registry.registry as registry_module
        from agno.db.base import BaseDb

        warnings = []
        monkeypatch.setattr(registry_module, "log_warning", lambda msg, *a, **k: warnings.append(msg))

        db = MagicMock(spec=BaseDb)
        db.id = "db-1"
        reg = Registry()
        reg.add_db(db)
        reg.add_db(db)
        assert len(reg.dbs) == 1 and warnings == []

    def test_add_vector_db_warns_when_dropping_matching_key(self, monkeypatch):
        import agno.registry.registry as registry_module
        from agno.vectordb.base import VectorDb

        warnings = []
        monkeypatch.setattr(registry_module, "log_warning", lambda msg, *a, **k: warnings.append(msg))

        v1 = MagicMock(spec=VectorDb)
        v1.id = None
        v1.name = "vec"
        v2 = MagicMock(spec=VectorDb)
        v2.id = None
        v2.name = "vec"  # same name, distinct instance
        reg = Registry()
        reg.add_vector_db(v1)
        reg.add_vector_db(v2)
        assert len(reg.vector_dbs) == 1 and reg.vector_dbs[0] is v1
        assert warnings and "vec" in warnings[0]

    def test_add_db_ignores_non_db(self):
        reg = Registry()
        reg.add_db(object())
        reg.add_db(None)
        assert reg.dbs == []

    def test_add_vector_db_dedupes_by_name(self):
        from agno.vectordb.base import VectorDb

        v1 = MagicMock(spec=VectorDb)
        v1.id = None
        v1.name = "vec"
        v2 = MagicMock(spec=VectorDb)
        v2.id = None
        v2.name = "vec"
        reg = Registry()
        reg.add_vector_db(v1)
        reg.add_vector_db(v2)
        assert len(reg.vector_dbs) == 1


class TestEntrypointLookupCollisionWarning:
    """The entrypoint lookup warns when distinct tools collide on a name."""

    def test_warns_on_distinct_tools_sharing_a_name(self, monkeypatch):
        import agno.registry.registry as registry_module

        warnings = []
        monkeypatch.setattr(registry_module, "log_warning", lambda msg, *a, **k: warnings.append(msg))

        def entrypoint_a():
            pass

        def entrypoint_b():
            pass

        reg = Registry(
            tools=[
                Function(name="search", entrypoint=entrypoint_a),
                Function(name="search", entrypoint=entrypoint_b),
            ]
        )
        # Build the lookup
        _ = reg._entrypoint_lookup

        assert warnings, "expected a warning for the ambiguous tool name"
        assert "search" in warnings[0]

    def test_no_warning_when_same_entrypoint_repeats(self, monkeypatch):
        import agno.registry.registry as registry_module

        warnings = []
        monkeypatch.setattr(registry_module, "log_warning", lambda msg, *a, **k: warnings.append(msg))

        def entrypoint_a():
            pass

        reg = Registry(
            tools=[
                Function(name="search", entrypoint=entrypoint_a),
                Function(name="search", entrypoint=entrypoint_a),  # same entrypoint object
            ]
        )
        _ = reg._entrypoint_lookup

        assert warnings == []

    def test_no_warning_for_unique_names(self, monkeypatch):
        import agno.registry.registry as registry_module

        warnings = []
        monkeypatch.setattr(registry_module, "log_warning", lambda msg, *a, **k: warnings.append(msg))

        def tool_a():
            pass

        def tool_b():
            pass

        reg = Registry(tools=[tool_a, tool_b])
        _ = reg._entrypoint_lookup

        assert warnings == []
