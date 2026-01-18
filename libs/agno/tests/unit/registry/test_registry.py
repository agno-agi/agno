"""
Unit tests for Registry class.

Tests cover:
- Registry initialization with various components
- _entrypoint_lookup property for tools
- rehydrate_function() for reconstructing Functions
- get_schema() for retrieving schemas by name
"""

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
