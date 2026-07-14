"""
Unit tests for the Registry router.

Tests cover:
- GET /registry - List registry components (tools, models, dbs, vector_dbs, schemas, functions)
"""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from agno.db.base import BaseDb
from agno.models.base import Model
from agno.os.routers.registry import get_registry_router
from agno.os.settings import AgnoAPISettings
from agno.registry import Registry
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit
from agno.vectordb.base import VectorDb

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


def _create_mock_vectordb_class():
    """Create a concrete VectorDb subclass with all abstract methods stubbed."""
    abstract_methods = {}
    for name in dir(VectorDb):
        attr = getattr(VectorDb, name, None)
        if getattr(attr, "__isabstractmethod__", False):
            abstract_methods[name] = MagicMock()
    return type("MockVectorDb", (VectorDb,), abstract_methods)


def _create_mock_model_class():
    """Create a concrete Model subclass with all abstract methods stubbed."""
    abstract_methods = {}
    for name in dir(Model):
        attr = getattr(Model, name, None)
        if getattr(attr, "__isabstractmethod__", False):
            abstract_methods[name] = MagicMock()
    return type("MockModel", (Model,), abstract_methods)


@pytest.fixture
def settings():
    """Create test settings with auth disabled (no security key = auth disabled)."""
    return AgnoAPISettings()


@pytest.fixture
def empty_registry():
    """Create an empty registry."""
    return Registry()


@pytest.fixture
def client_with_empty_registry(empty_registry, settings):
    """Create a FastAPI test client with empty registry."""
    app = FastAPI()
    router = get_registry_router(registry=empty_registry, settings=settings)
    app.include_router(router)
    return TestClient(app)


# =============================================================================
# List Registry Tests - Empty Registry
# =============================================================================


class TestListRegistryEmpty:
    """Tests for GET /registry endpoint with empty registry."""

    def test_list_registry_empty(self, client_with_empty_registry):
        """Test list_registry returns empty list for empty registry."""
        response = client_with_empty_registry.get("/registry")

        assert response.status_code == 200
        data = response.json()
        assert data["data"] == []
        assert data["meta"]["total_count"] == 0

    def test_list_registry_pagination_info(self, client_with_empty_registry):
        """Test list_registry returns correct pagination info."""
        response = client_with_empty_registry.get("/registry?page=1&limit=10")

        assert response.status_code == 200
        data = response.json()
        assert data["meta"]["page"] == 1
        assert data["meta"]["limit"] == 10
        assert data["meta"]["total_pages"] == 0


# =============================================================================
# List Registry Tests - With Tools
# =============================================================================


class TestListRegistryWithTools:
    """Tests for GET /registry endpoint with tools."""

    def test_list_registry_with_function(self, settings):
        """Test list_registry includes Function tools."""

        def my_tool(x: int) -> int:
            """A test tool."""
            return x * 2

        func = Function(
            name="my_tool",
            description="A test tool",
            entrypoint=my_tool,
        )
        registry = Registry(tools=[func])

        app = FastAPI()
        router = get_registry_router(registry=registry, settings=settings)
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/registry")

        assert response.status_code == 200
        data = response.json()
        assert data["meta"]["total_count"] >= 1

        # Find the tool in the response
        tools = [c for c in data["data"] if c["type"] == "tool"]
        assert len(tools) >= 1
        tool_names = [t["name"] for t in tools]
        assert "my_tool" in tool_names

    def test_list_registry_with_toolkit(self, settings):
        """Test list_registry includes Toolkit with embedded functions."""

        class MyToolkit(Toolkit):
            def __init__(self):
                super().__init__(name="my_toolkit")
                self.description = "A test toolkit"
                self.register(self.tool_one)
                self.register(self.tool_two)

            def tool_one(self, x: int) -> int:
                """First tool."""
                return x + 1

            def tool_two(self, y: str) -> str:
                """Second tool."""
                return y.upper()

        toolkit = MyToolkit()
        registry = Registry(tools=[toolkit])

        app = FastAPI()
        router = get_registry_router(registry=registry, settings=settings)
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/registry")

        assert response.status_code == 200
        data = response.json()

        # Toolkit is returned as type="tool" with is_toolkit=True
        tools = [c for c in data["data"] if c["type"] == "tool"]
        assert len(tools) == 1
        assert tools[0]["name"] == "my_toolkit"
        assert tools[0]["metadata"]["is_toolkit"] is True

        # Functions are embedded in metadata
        functions = tools[0]["metadata"]["functions"]
        assert len(functions) == 2
        func_names = [f["name"] for f in functions]
        assert "tool_one" in func_names
        assert "tool_two" in func_names

    def test_list_registry_with_callable(self, settings):
        """Test list_registry includes callable tools."""

        def simple_function(x: int) -> int:
            """A simple function."""
            return x * 2

        registry = Registry(tools=[simple_function])

        app = FastAPI()
        router = get_registry_router(registry=registry, settings=settings)
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/registry")

        assert response.status_code == 200
        data = response.json()

        tools = [c for c in data["data"] if c["type"] == "tool"]
        assert len(tools) >= 1
        tool_names = [t["name"] for t in tools]
        assert "simple_function" in tool_names


# =============================================================================
# List Registry Tests - With Models
# =============================================================================


class TestListRegistryWithModels:
    """Tests for GET /registry endpoint with models."""

    def test_list_registry_with_model(self, settings):
        """Test list_registry includes models."""
        MockModelClass = _create_mock_model_class()
        model = MockModelClass(id="gpt-4")
        model.name = "GPT-4"
        model.provider = "OpenAI"

        registry = Registry(models=[model])

        app = FastAPI()
        router = get_registry_router(registry=registry, settings=settings)
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/registry")

        assert response.status_code == 200
        data = response.json()

        models = [c for c in data["data"] if c["type"] == "model"]
        assert len(models) == 1
        assert models[0]["name"] == "gpt-4"
        assert models[0]["metadata"]["provider"] == "OpenAI"


# =============================================================================
# List Registry Tests - With Databases
# =============================================================================


class TestListRegistryWithDatabases:
    """Tests for GET /registry endpoint with databases."""

    def test_list_registry_with_db(self, settings):
        """Test list_registry includes databases."""
        MockDbClass = _create_mock_db_class()
        db = MockDbClass()
        db.id = "main-db"
        db.name = "Main Database"

        registry = Registry(dbs=[db])

        app = FastAPI()
        router = get_registry_router(registry=registry, settings=settings)
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/registry")

        assert response.status_code == 200
        data = response.json()

        dbs = [c for c in data["data"] if c["type"] == "db"]
        assert len(dbs) == 1
        assert dbs[0]["name"] == "Main Database"
        assert dbs[0]["metadata"]["db_id"] == "main-db"

    def test_list_registry_with_vector_db(self, settings):
        """Test list_registry includes vector databases."""
        MockVectorDbClass = _create_mock_vectordb_class()
        vdb = MockVectorDbClass()
        vdb.id = "vectors-db"
        vdb.name = "Vectors"
        vdb.collection = "embeddings"

        registry = Registry(vector_dbs=[vdb])

        app = FastAPI()
        router = get_registry_router(registry=registry, settings=settings)
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/registry")

        assert response.status_code == 200
        data = response.json()

        vdbs = [c for c in data["data"] if c["type"] == "vector_db"]
        assert len(vdbs) == 1
        assert vdbs[0]["name"] == "Vectors"
        assert vdbs[0]["metadata"]["collection"] == "embeddings"


# =============================================================================
# List Registry Tests - With Schemas
# =============================================================================


class TestListRegistryWithSchemas:
    """Tests for GET /registry endpoint with schemas."""

    def test_list_registry_with_schema(self, settings):
        """Test list_registry includes schemas."""

        class UserInput(BaseModel):
            name: str
            age: int

        registry = Registry(schemas=[UserInput])

        app = FastAPI()
        router = get_registry_router(registry=registry, settings=settings)
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/registry")

        assert response.status_code == 200
        data = response.json()

        schemas = [c for c in data["data"] if c["type"] == "schema"]
        assert len(schemas) == 1
        assert schemas[0]["name"] == "UserInput"

    def test_list_registry_with_schema_includes_json_schema(self, settings):
        """Test list_registry includes JSON schema when requested."""

        class UserInput(BaseModel):
            name: str
            age: int

        registry = Registry(schemas=[UserInput])

        app = FastAPI()
        router = get_registry_router(registry=registry, settings=settings)
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/registry?include_schema=true")

        assert response.status_code == 200
        data = response.json()

        schemas = [c for c in data["data"] if c["type"] == "schema"]
        assert len(schemas) == 1
        assert "schema" in schemas[0]["metadata"]
        assert "properties" in schemas[0]["metadata"]["schema"]


# =============================================================================
# List Registry Tests - Filtering
# =============================================================================


class TestListRegistryFiltering:
    """Tests for GET /registry endpoint filtering."""

    def test_list_registry_filter_by_type(self, settings):
        """Test list_registry filters by resource_type."""

        def my_tool():
            pass

        MockDbClass = _create_mock_db_class()
        db = MockDbClass()
        db.id = "test-db"
        db.name = "Test DB"

        registry = Registry(tools=[my_tool], dbs=[db])

        app = FastAPI()
        router = get_registry_router(registry=registry, settings=settings)
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/registry?resource_type=db")

        assert response.status_code == 200
        data = response.json()

        # Should only return db components
        assert all(c["type"] == "db" for c in data["data"])
        assert data["meta"]["total_count"] == 1

    def test_list_registry_filter_by_name(self, settings):
        """Test list_registry filters by name (partial match)."""

        def search_tool():
            """Search tool."""
            pass

        def fetch_tool():
            """Fetch tool."""
            pass

        registry = Registry(tools=[search_tool, fetch_tool])

        app = FastAPI()
        router = get_registry_router(registry=registry, settings=settings)
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/registry?name=search")

        assert response.status_code == 200
        data = response.json()

        # Should only return components with "search" in the name
        assert data["meta"]["total_count"] == 1
        assert "search" in data["data"][0]["name"].lower()


# =============================================================================
# List Registry Tests - Pagination
# =============================================================================


class TestListRegistryPagination:
    """Tests for GET /registry endpoint pagination."""

    def test_list_registry_pagination(self, settings):
        """Test list_registry paginates results."""
        # Create multiple tools
        tools = []
        for i in range(25):
            func = Function(name=f"tool_{i:02d}", description=f"Tool {i}")
            tools.append(func)

        registry = Registry(tools=tools)

        app = FastAPI()
        router = get_registry_router(registry=registry, settings=settings)
        app.include_router(router)
        client = TestClient(app)

        # Get first page
        response = client.get("/registry?page=1&limit=10")

        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 10
        assert data["meta"]["page"] == 1
        assert data["meta"]["total_count"] == 25
        assert data["meta"]["total_pages"] == 3

        # Get second page
        response = client.get("/registry?page=2&limit=10")

        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 10
        assert data["meta"]["page"] == 2

        # Get last page
        response = client.get("/registry?page=3&limit=10")

        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 5  # Only 5 remaining
        assert data["meta"]["page"] == 3


# =============================================================================
# List Registry Tests - Mixed Components
# =============================================================================


class TestListRegistryMixed:
    """Tests for GET /registry endpoint with mixed components."""

    def test_list_registry_mixed_components(self, settings):
        """Test list_registry with all component types."""

        def my_tool():
            """A tool."""
            pass

        class MySchema(BaseModel):
            field: str

        MockDbClass = _create_mock_db_class()
        db = MockDbClass()
        db.id = "test-db"
        db.name = "Test DB"

        MockVectorDbClass = _create_mock_vectordb_class()
        vdb = MockVectorDbClass()
        vdb.id = "test-vdb"
        vdb.name = "Test VDB"
        vdb.collection = "test"

        MockModelClass = _create_mock_model_class()
        model = MockModelClass(id="test-model")
        model.name = "Test Model"
        model.provider = "Test"

        registry = Registry(
            tools=[my_tool],
            models=[model],
            dbs=[db],
            vector_dbs=[vdb],
            schemas=[MySchema],
        )

        app = FastAPI()
        router = get_registry_router(registry=registry, settings=settings)
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/registry")

        assert response.status_code == 200
        data = response.json()

        # Should have all component types
        component_types = set(c["type"] for c in data["data"])
        assert "tool" in component_types
        assert "model" in component_types
        assert "db" in component_types
        assert "vector_db" in component_types
        assert "schema" in component_types

    def test_list_registry_sorted_by_type_and_name(self, settings):
        """Test list_registry results are sorted by type and name."""

        def z_tool():
            pass

        def a_tool():
            pass

        MockDbClass = _create_mock_db_class()
        db = MockDbClass()
        db.id = "a-db"
        db.name = "A DB"

        registry = Registry(tools=[z_tool, a_tool], dbs=[db])

        app = FastAPI()
        router = get_registry_router(registry=registry, settings=settings)
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/registry")

        assert response.status_code == 200
        data = response.json()

        # Results should be sorted by (component_type, name)
        # db comes before tool alphabetically
        types = [c["type"] for c in data["data"]]
        assert types == sorted(types)


# =============================================================================
# List Registry Tests - With Knowledge
# =============================================================================


class TestListRegistryWithKnowledge:
    """Tests for GET /registry endpoint with knowledge instances."""

    def test_list_registry_with_knowledge(self, settings):
        """Test list_registry includes knowledge instances."""
        kb = MagicMock()
        kb.name = "Docs KB"
        kb.description = "Documentation knowledge base"
        kb.max_results = 7
        kb.readers = {"pdf": MagicMock(), "text": MagicMock()}
        kb.vector_db = MagicMock()
        kb.contents_db = MagicMock()

        registry = Registry(knowledge=[kb])

        app = FastAPI()
        router = get_registry_router(registry=registry, settings=settings)
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/registry")

        assert response.status_code == 200
        data = response.json()

        knowledge = [c for c in data["data"] if c["type"] == "knowledge"]
        assert len(knowledge) == 1
        assert knowledge[0]["name"] == "Docs KB"
        assert knowledge[0]["description"] == "Documentation knowledge base"
        assert knowledge[0]["metadata"]["max_results"] == 7
        assert knowledge[0]["metadata"]["num_readers"] == 2

    def test_list_registry_filter_by_knowledge(self, settings):
        """Test filtering registry by knowledge resource type."""
        kb = MagicMock()
        kb.name = "Docs KB"
        kb.description = None
        kb.readers = None
        kb.vector_db = None
        kb.contents_db = None

        def my_tool():
            pass

        registry = Registry(knowledge=[kb], tools=[my_tool])

        app = FastAPI()
        router = get_registry_router(registry=registry, settings=settings)
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/registry?resource_type=knowledge")

        assert response.status_code == 200
        data = response.json()
        assert all(c["type"] == "knowledge" for c in data["data"])
        assert data["meta"]["total_count"] == 1

    def test_num_readers_counts_list_readers(self, settings):
        """num_readers is computed when readers is a list (not only a dict)."""
        kb = MagicMock()
        kb.name = "List Readers KB"
        kb.description = None
        kb.readers = [MagicMock(), MagicMock(), MagicMock()]
        kb.vector_db = None
        kb.contents_db = None
        kb.max_results = None

        registry = Registry(knowledge=[kb])

        app = FastAPI()
        router = get_registry_router(registry=registry, settings=settings)
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/registry?resource_type=knowledge")

        assert response.status_code == 200
        data = response.json()
        knowledge = [c for c in data["data"] if c["type"] == "knowledge"]
        assert len(knowledge) == 1
        assert knowledge[0]["metadata"]["num_readers"] == 3

    def test_num_readers_unexpected_type_does_not_crash(self, settings):
        """An unexpected non-sized readers value yields no num_readers (no crash)."""
        kb = MagicMock()
        kb.name = "Weird Readers KB"
        kb.description = None
        kb.readers = 42  # not a dict or list, and not sized
        kb.vector_db = None
        kb.contents_db = None
        kb.max_results = None

        registry = Registry(knowledge=[kb])

        app = FastAPI()
        router = get_registry_router(registry=registry, settings=settings)
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/registry?resource_type=knowledge")

        assert response.status_code == 200
        data = response.json()
        knowledge = [c for c in data["data"] if c["type"] == "knowledge"]
        assert len(knowledge) == 1
        # num_readers omitted (None excluded by model_dump(exclude_none=True))
        assert "num_readers" not in knowledge[0]["metadata"]


# =============================================================================
# List Registry Tests - With Managers
# =============================================================================


class TestListRegistryWithManagers:
    """Tests for GET /registry endpoint with memory/session summary managers."""

    def test_list_registry_with_memory_manager(self, settings):
        """Test list_registry includes memory managers with metadata."""
        from agno.memory.manager import MemoryManager

        mm = MemoryManager(id="mm-1", name="My Memory", add_memories=True)

        registry = Registry(memory_managers=[mm])

        app = FastAPI()
        router = get_registry_router(registry=registry, settings=settings)
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/registry")

        assert response.status_code == 200
        data = response.json()

        managers = [c for c in data["data"] if c["type"] == "memory_manager"]
        assert len(managers) == 1
        assert managers[0]["id"] == "mm-1"
        assert managers[0]["name"] == "My Memory"
        assert managers[0]["metadata"]["add_memories"] is True

    def test_list_registry_with_session_summary_manager(self, settings):
        """Test list_registry includes session summary managers with metadata."""
        from agno.session.summary import SessionSummaryManager

        sm = SessionSummaryManager(id="sm-1", name="Concise", last_n_runs=10)

        registry = Registry(session_summary_managers=[sm])

        app = FastAPI()
        router = get_registry_router(registry=registry, settings=settings)
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/registry")

        assert response.status_code == 200
        data = response.json()

        managers = [c for c in data["data"] if c["type"] == "session_summary_manager"]
        assert len(managers) == 1
        assert managers[0]["id"] == "sm-1"
        assert managers[0]["name"] == "Concise"
        assert managers[0]["metadata"]["last_n_runs"] == 10

    def test_two_session_summary_managers_have_distinct_ids(self, settings):
        """Test that two managers without explicit id are not collapsed (duplicate-id fix)."""
        from agno.session.summary import SessionSummaryManager

        sm1 = SessionSummaryManager(last_n_runs=10)
        sm2 = SessionSummaryManager(conversation_limit=50)

        registry = Registry(session_summary_managers=[sm1, sm2])

        app = FastAPI()
        router = get_registry_router(registry=registry, settings=settings)
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/registry?resource_type=session_summary_manager")

        assert response.status_code == 200
        data = response.json()

        managers = [c for c in data["data"] if c["type"] == "session_summary_manager"]
        assert len(managers) == 2
        ids = {m["id"] for m in managers}
        assert len(ids) == 2
