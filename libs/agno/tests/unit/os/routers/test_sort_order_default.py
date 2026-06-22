"""
Integration tests for sort_order default value in RemoteDb routes.

Validates that sort_order query parameter defaults to SortOrder.DESC (not a raw string)
across all four affected routers: session, memory, evals, knowledge.

Uses FastAPI TestClient to exercise the real ASGI stack end-to-end.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agno.os.schema import SortOrder

# ---------------------------------------------------------------------------
# Helpers – create mock DB / Knowledge with only the methods each router needs
# ---------------------------------------------------------------------------


def _make_async_db():
    """Create an AsyncBaseDb mock that passes isinstance checks."""
    from agno.db.base import AsyncBaseDb

    mock = MagicMock(spec=AsyncBaseDb)
    mock.id = "test-db"

    # get_sessions returns (list[dict], int)
    mock.get_sessions = AsyncMock(return_value=([], 0))
    # get_user_memories returns (list[dict], int)
    mock.get_user_memories = AsyncMock(return_value=([], 0))
    # get_eval_runs returns (list[dict], int)
    mock.get_eval_runs = AsyncMock(return_value=([], 0))
    return mock


def _make_knowledge():
    """Create a Knowledge mock that passes isinstance checks."""
    from agno.knowledge.knowledge import Knowledge

    mock = MagicMock(spec=Knowledge)
    mock.name = "test-kb"
    mock.id = "test-kb-id"
    mock.db_id = "test-db"
    mock.knowledge_id = "test-kb-id"
    # aget_content returns (list[Content], int)
    mock.aget_content = AsyncMock(return_value=([], 0))
    return mock


def _build_app_with_session_router(db):
    from agno.os.routers.session import get_session_router
    from agno.os.settings import AgnoAPISettings

    app = FastAPI()
    router = get_session_router(dbs={"test-db": [db]}, settings=AgnoAPISettings())
    app.include_router(router)
    return app


def _build_app_with_memory_router(db):
    from agno.os.routers.memory import get_memory_router
    from agno.os.settings import AgnoAPISettings

    app = FastAPI()
    router = get_memory_router(dbs={"test-db": [db]}, settings=AgnoAPISettings())
    app.include_router(router)
    return app


def _build_app_with_eval_router(db):
    from agno.os.routers.evals import get_eval_router
    from agno.os.settings import AgnoAPISettings

    app = FastAPI()
    router = get_eval_router(dbs={"test-db": [db]}, settings=AgnoAPISettings())
    app.include_router(router)
    return app


def _build_app_with_knowledge_router(knowledge):
    from agno.os.routers.knowledge import get_knowledge_router
    from agno.os.settings import AgnoAPISettings

    app = FastAPI()
    router = get_knowledge_router(knowledge_instances=[knowledge], settings=AgnoAPISettings())
    app.include_router(router)
    return app


# =============================================================================
# Session Router – sort_order tests
# =============================================================================


class TestSessionSortOrder:
    """Test sort_order parameter in GET /sessions."""

    @pytest.fixture
    def db(self):
        return _make_async_db()

    @pytest.fixture
    def client(self, db):
        return TestClient(_build_app_with_session_router(db))

    def test_default_sort_order_is_desc(self, client, db):
        """When sort_order is omitted, the endpoint should pass SortOrder.DESC to the DB."""
        response = client.get("/sessions?type=agent&db_id=test-db")
        assert response.status_code == 200

        db.get_sessions.assert_called_once()
        call_kwargs = db.get_sessions.call_args.kwargs
        assert call_kwargs["sort_order"] is SortOrder.DESC

    def test_explicit_asc_sort_order(self, client, db):
        """When sort_order=asc is passed, the endpoint should use SortOrder.ASC."""
        response = client.get("/sessions?type=agent&db_id=test-db&sort_order=asc")
        assert response.status_code == 200

        db.get_sessions.assert_called_once()
        call_kwargs = db.get_sessions.call_args.kwargs
        assert call_kwargs["sort_order"] is SortOrder.ASC

    def test_explicit_desc_sort_order(self, client, db):
        """When sort_order=desc is passed, the endpoint should use SortOrder.DESC."""
        response = client.get("/sessions?type=agent&db_id=test-db&sort_order=desc")
        assert response.status_code == 200

        db.get_sessions.assert_called_once()
        call_kwargs = db.get_sessions.call_args.kwargs
        assert call_kwargs["sort_order"] is SortOrder.DESC

    def test_invalid_sort_order_rejected(self, client):
        """An invalid sort_order value should be rejected with 422."""
        response = client.get("/sessions?type=agent&db_id=test-db&sort_order=invalid")
        assert response.status_code == 422

    def test_sort_order_type_is_enum_not_string(self, client, db):
        """Verify the default is an actual SortOrder enum, not a plain string."""
        client.get("/sessions?type=agent&db_id=test-db")

        call_kwargs = db.get_sessions.call_args.kwargs
        assert isinstance(call_kwargs["sort_order"], SortOrder)
        assert not isinstance(call_kwargs["sort_order"], str) or type(call_kwargs["sort_order"]) is SortOrder


# =============================================================================
# Memory Router – sort_order tests
# =============================================================================


class TestMemorySortOrder:
    """Test sort_order parameter in GET /memories."""

    @pytest.fixture
    def db(self):
        return _make_async_db()

    @pytest.fixture
    def client(self, db):
        return TestClient(_build_app_with_memory_router(db))

    def test_default_sort_order_is_desc(self, client, db):
        """When sort_order is omitted, the endpoint should pass SortOrder.DESC to the DB."""
        response = client.get("/memories?db_id=test-db")
        assert response.status_code == 200

        db.get_user_memories.assert_called_once()
        call_kwargs = db.get_user_memories.call_args.kwargs
        assert call_kwargs["sort_order"] is SortOrder.DESC

    def test_explicit_asc_sort_order(self, client, db):
        """When sort_order=asc is passed, the endpoint should use SortOrder.ASC."""
        response = client.get("/memories?db_id=test-db&sort_order=asc")
        assert response.status_code == 200

        db.get_user_memories.assert_called_once()
        call_kwargs = db.get_user_memories.call_args.kwargs
        assert call_kwargs["sort_order"] is SortOrder.ASC

    def test_explicit_desc_sort_order(self, client, db):
        """When sort_order=desc is passed, the endpoint should use SortOrder.DESC."""
        response = client.get("/memories?db_id=test-db&sort_order=desc")
        assert response.status_code == 200

        db.get_user_memories.assert_called_once()
        call_kwargs = db.get_user_memories.call_args.kwargs
        assert call_kwargs["sort_order"] is SortOrder.DESC

    def test_invalid_sort_order_rejected(self, client):
        """An invalid sort_order value should be rejected with 422."""
        response = client.get("/memories?db_id=test-db&sort_order=invalid")
        assert response.status_code == 422

    def test_sort_order_type_is_enum_not_string(self, client, db):
        """Verify the default is an actual SortOrder enum, not a plain string."""
        client.get("/memories?db_id=test-db")

        call_kwargs = db.get_user_memories.call_args.kwargs
        assert isinstance(call_kwargs["sort_order"], SortOrder)


# =============================================================================
# Evals Router – sort_order tests
# =============================================================================


class TestEvalsSortOrder:
    """Test sort_order parameter in GET /eval-runs."""

    @pytest.fixture
    def db(self):
        return _make_async_db()

    @pytest.fixture
    def client(self, db):
        return TestClient(_build_app_with_eval_router(db))

    def test_default_sort_order_is_desc(self, client, db):
        """When sort_order is omitted, the endpoint should pass SortOrder.DESC to the DB."""
        response = client.get("/eval-runs?db_id=test-db")
        assert response.status_code == 200

        db.get_eval_runs.assert_called_once()
        call_kwargs = db.get_eval_runs.call_args.kwargs
        assert call_kwargs["sort_order"] is SortOrder.DESC

    def test_explicit_asc_sort_order(self, client, db):
        """When sort_order=asc is passed, the endpoint should use SortOrder.ASC."""
        response = client.get("/eval-runs?db_id=test-db&sort_order=asc")
        assert response.status_code == 200

        db.get_eval_runs.assert_called_once()
        call_kwargs = db.get_eval_runs.call_args.kwargs
        assert call_kwargs["sort_order"] is SortOrder.ASC

    def test_explicit_desc_sort_order(self, client, db):
        """When sort_order=desc is passed, the endpoint should use SortOrder.DESC."""
        response = client.get("/eval-runs?db_id=test-db&sort_order=desc")
        assert response.status_code == 200

        db.get_eval_runs.assert_called_once()
        call_kwargs = db.get_eval_runs.call_args.kwargs
        assert call_kwargs["sort_order"] is SortOrder.DESC

    def test_invalid_sort_order_rejected(self, client):
        """An invalid sort_order value should be rejected with 422."""
        response = client.get("/eval-runs?db_id=test-db&sort_order=invalid")
        assert response.status_code == 422

    def test_sort_order_type_is_enum_not_string(self, client, db):
        """Verify the default is an actual SortOrder enum, not a plain string."""
        client.get("/eval-runs?db_id=test-db")

        call_kwargs = db.get_eval_runs.call_args.kwargs
        assert isinstance(call_kwargs["sort_order"], SortOrder)


# =============================================================================
# Knowledge Router – sort_order tests
# =============================================================================


class TestKnowledgeSortOrder:
    """Test sort_order parameter in GET /knowledge/content."""

    @pytest.fixture
    def knowledge(self):
        return _make_knowledge()

    @pytest.fixture
    def client(self, knowledge):
        return TestClient(_build_app_with_knowledge_router(knowledge))

    def test_default_sort_order_is_desc(self, client, knowledge):
        """When sort_order is omitted, the endpoint should pass SortOrder.DESC to knowledge."""
        response = client.get("/knowledge/content")
        assert response.status_code == 200

        knowledge.aget_content.assert_called_once()
        call_kwargs = knowledge.aget_content.call_args.kwargs
        assert call_kwargs["sort_order"] is SortOrder.DESC

    def test_explicit_asc_sort_order(self, client, knowledge):
        """When sort_order=asc is passed, the endpoint should use SortOrder.ASC."""
        response = client.get("/knowledge/content?sort_order=asc")
        assert response.status_code == 200

        knowledge.aget_content.assert_called_once()
        call_kwargs = knowledge.aget_content.call_args.kwargs
        assert call_kwargs["sort_order"] is SortOrder.ASC

    def test_explicit_desc_sort_order(self, client, knowledge):
        """When sort_order=desc is passed, the endpoint should use SortOrder.DESC."""
        response = client.get("/knowledge/content?sort_order=desc")
        assert response.status_code == 200

        knowledge.aget_content.assert_called_once()
        call_kwargs = knowledge.aget_content.call_args.kwargs
        assert call_kwargs["sort_order"] is SortOrder.DESC

    def test_invalid_sort_order_rejected(self, client):
        """An invalid sort_order value should be rejected with 422."""
        response = client.get("/knowledge/content?sort_order=invalid")
        assert response.status_code == 422

    def test_sort_order_type_is_enum_not_string(self, client, knowledge):
        """Verify the default is an actual SortOrder enum, not a plain string."""
        client.get("/knowledge/content")

        call_kwargs = knowledge.aget_content.call_args.kwargs
        assert isinstance(call_kwargs["sort_order"], SortOrder)
