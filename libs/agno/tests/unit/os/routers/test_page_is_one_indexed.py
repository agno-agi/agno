"""``page`` is 1-indexed, so ``page=0`` must be rejected at the query boundary.

Six list endpoints declared ``page`` as ``ge=0`` while documenting it as
1-indexed, so ``page=0`` passed validation and reached the DB layer. What
happened there depended on the adapter:

- adapters that call ``agno.db.utils.validate_pagination`` (every SQL one)
  raised ``ValueError`` mid-request, so ``/sessions``, ``/memories``,
  ``/user_memory_stats``, ``/eval-runs`` and ``/knowledge/content`` answered
  500;
- everything else computed ``(0 - 1) * limit``, sliced with a negative index
  and answered 200 with a silently empty page and ``meta.page: 0`` — that is
  what ``/traces`` did on every backend, and what ``InMemoryDb``/``JsonDb``
  did for the other five.

Sibling endpoints (``/queue/jobs``, ``/schedules``, ``/approvals``,
``/traces/search``, ...) already declare ``ge=1`` and answer 422.
"""

from __future__ import annotations

import tempfile
import time
from typing import Any, Callable, Dict, NamedTuple
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from agno.db.sqlite import SqliteDb
from agno.os.settings import AgnoAPISettings
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession


def _mock_async_db() -> Any:
    """An AsyncBaseDb whose reads succeed, so a non-422 means the parameter got through."""
    from agno.db.base import AsyncBaseDb

    db = MagicMock(spec=AsyncBaseDb)
    db.id = "test-db"
    db.get_sessions = AsyncMock(return_value=([], 0))
    db.get_user_memories = AsyncMock(return_value=([], 0))
    db.get_user_memory_stats = AsyncMock(return_value=([], 0))
    db.get_eval_runs = AsyncMock(return_value=([], 0))
    db.get_traces = AsyncMock(return_value=([], 0))
    return db


def _mock_knowledge() -> Any:
    from agno.knowledge.knowledge import Knowledge

    kb = MagicMock(spec=Knowledge)
    kb.name = "test-kb"
    kb.id = "test-kb-id"
    kb.knowledge_id = "test-kb-id"
    kb.db_id = "test-db"
    kb.aget_content = AsyncMock(return_value=([], 0))
    return kb


def _client(router: APIRouter) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


class Endpoint(NamedTuple):
    path: str
    params: Dict[str, Any]
    build: Callable[[], APIRouter]


def _session_router() -> APIRouter:
    from agno.os.routers.session import get_session_router

    return get_session_router(dbs={"test-db": [_mock_async_db()]}, settings=AgnoAPISettings())


def _memory_router() -> APIRouter:
    from agno.os.routers.memory import get_memory_router

    return get_memory_router(dbs={"test-db": [_mock_async_db()]}, settings=AgnoAPISettings())


def _eval_router() -> APIRouter:
    from agno.os.routers.evals import get_eval_router

    return get_eval_router(dbs={"test-db": [_mock_async_db()]}, settings=AgnoAPISettings())


def _traces_router() -> APIRouter:
    from agno.os.routers.traces import get_traces_router

    return get_traces_router(dbs={"test-db": [_mock_async_db()]}, settings=AgnoAPISettings())


def _knowledge_router() -> APIRouter:
    from agno.os.routers.knowledge import get_knowledge_router

    return get_knowledge_router(knowledge_instances=[_mock_knowledge()], settings=AgnoAPISettings())


ENDPOINTS = {
    "GET /sessions": Endpoint("/sessions", {"db_id": "test-db", "type": "agent"}, _session_router),
    "GET /memories": Endpoint("/memories", {"db_id": "test-db"}, _memory_router),
    "GET /user_memory_stats": Endpoint("/user_memory_stats", {"db_id": "test-db"}, _memory_router),
    "GET /eval-runs": Endpoint("/eval-runs", {"db_id": "test-db"}, _eval_router),
    "GET /knowledge/content": Endpoint("/knowledge/content", {}, _knowledge_router),
    "GET /traces": Endpoint("/traces", {"db_id": "test-db"}, _traces_router),
}


@pytest.fixture(params=sorted(ENDPOINTS), ids=sorted(ENDPOINTS))
def endpoint(request) -> Endpoint:
    """One freshly built router + client per test, not one shared at collection time."""
    return ENDPOINTS[request.param]


class TestPageIsOneIndexed:
    def test_page_zero_is_rejected(self, endpoint: Endpoint):
        response = _client(endpoint.build()).get(endpoint.path, params={**endpoint.params, "page": 0, "limit": 2})
        assert response.status_code == 422
        assert any(err["loc"][-1] == "page" for err in response.json()["detail"])

    def test_first_page_still_works(self, endpoint: Endpoint):
        response = _client(endpoint.build()).get(endpoint.path, params={**endpoint.params, "page": 1, "limit": 2})
        assert response.status_code == 200, response.text[:200]


def _sqlite_with_sessions() -> SqliteDb:
    db = SqliteDb(db_file=tempfile.mktemp(suffix=".db"))
    now = int(time.time())
    for i in range(3):
        session = AgentSession(
            session_id=f"s{i}",
            agent_id="a1",
            user_id="user-1",
            session_data={"session_name": f"chat {i}"},
            created_at=now,
            updated_at=now,
        )
        session.upsert_run(RunOutput(run_id=f"r{i}", agent_id="a1", user_id="user-1", status=RunStatus.completed))
        db.upsert_session(session)
    return db


class TestPageZeroNoLongerReachesTheDatabase:
    """End-to-end against a real SQL adapter: these two requests were 500s,
    because ``validate_pagination`` raised inside the adapter mid-request."""

    def test_sessions_page_zero_is_422_not_500(self):
        from agno.os.routers.session import get_session_router

        client = _client(get_session_router(dbs={"default": [_sqlite_with_sessions()]}, settings=AgnoAPISettings()))
        assert client.get("/sessions?user_id=user-1&page=0&limit=2").status_code == 422

    def test_knowledge_content_page_zero_is_422_not_500(self):
        from agno.knowledge.knowledge import Knowledge
        from agno.os.routers.knowledge import get_knowledge_router

        db = SqliteDb(db_file=tempfile.mktemp(suffix=".db"))
        # The 500 needed the knowledge table to exist; otherwise get_knowledge_contents
        # short-circuits on `table is None` before it validates.
        db._get_table(table_type="knowledge", create_table_if_not_found=True)
        knowledge = Knowledge(name="kb", contents_db=db)
        client = _client(get_knowledge_router(knowledge_instances=[knowledge], settings=AgnoAPISettings()))
        assert client.get("/knowledge/content?page=0&limit=2").status_code == 422

    def test_valid_pages_are_unaffected(self):
        from agno.os.routers.session import get_session_router

        client = _client(get_session_router(dbs={"default": [_sqlite_with_sessions()]}, settings=AgnoAPISettings()))
        first = client.get("/sessions?user_id=user-1&page=1&limit=2")
        second = client.get("/sessions?user_id=user-1&page=2&limit=2")
        assert first.status_code == 200 and second.status_code == 200
        assert len(first.json()["data"]) == 2
        assert len(second.json()["data"]) == 1
