"""REST tests for paginated GET /sessions/{id}/runs (#8805).

Verifies offset/limit paging surfaces via response headers (X-Total-Count /
X-Has-More) while the default (no limit) response stays a flat list for
backward compatibility.
"""

import time
import uuid

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from agno.db.in_memory.in_memory_db import InMemoryDb
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession


def _build_client(db):
    from agno.os.routers.session.session import attach_routes

    app = FastAPI()
    router = APIRouter()
    attach_routes(router, {"default": [db]})
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def db_with_many_runs():
    """An InMemoryDb with one agent session holding 5 runs."""
    db = InMemoryDb()
    uid = uuid.uuid4().hex[:8]
    now = int(time.time())
    session = AgentSession(
        session_id=f"agent-{uid}",
        agent_id="test-agent",
        user_id="user-1",
        created_at=now,
        updated_at=now,
        runs=[
            RunOutput(
                run_id=f"run-{i}-{uid}",
                agent_id="test-agent",
                user_id="user-1",
                status=RunStatus.completed,
                messages=[],
                created_at=now + i,
            )
            for i in range(5)
        ],
    )
    db.upsert_session(session)
    return db, session


class TestSessionRunsPagination:
    def test_no_limit_returns_all_as_flat_list(self, db_with_many_runs):
        """Default behavior unchanged: no pagination headers, full list body."""
        db, session = db_with_many_runs
        client = _build_client(db)

        resp = client.get(f"/sessions/{session.session_id}/runs?type=agent&user_id=user-1")

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) == 5
        # No pagination headers emitted in the default path.
        assert "x-total-count" not in {k.lower() for k in resp.headers}

    def test_limit_returns_page_and_total_count_header(self, db_with_many_runs):
        db, session = db_with_many_runs
        client = _build_client(db)

        resp = client.get(f"/sessions/{session.session_id}/runs?type=agent&user_id=user-1&limit=2")

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) == 2  # page size
        assert resp.headers["x-total-count"] == "5"
        assert resp.headers["x-has-more"] == "true"
        assert resp.headers["x-limit"] == "2"
        assert resp.headers["x-offset"] == "0"

    def test_offset_advances_page(self, db_with_many_runs):
        db, session = db_with_many_runs
        client = _build_client(db)

        resp = client.get(f"/sessions/{session.session_id}/runs?type=agent&user_id=user-1&limit=2&offset=2")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 2
        assert resp.headers["x-total-count"] == "5"
        assert resp.headers["x-has-more"] == "true"

    def test_last_partial_page_has_more_false(self, db_with_many_runs):
        db, session = db_with_many_runs
        client = _build_client(db)

        resp = client.get(f"/sessions/{session.session_id}/runs?type=agent&user_id=user-1&limit=2&offset=4")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1  # only the 5th run
        assert resp.headers["x-total-count"] == "5"
        assert resp.headers["x-has-more"] == "false"

    def test_pagination_applies_after_timestamp_filter(self, db_with_many_runs):
        db, session = db_with_many_runs
        client = _build_client(db)
        # created_at values are now..now+4; created_after keeps runs with created_at >=
        # cutoff. Pick runs[2] (now+2) so the last 3 runs survive the filter.
        cutoff = int(session.runs[2].created_at)

        resp = client.get(
            f"/sessions/{session.session_id}/runs?type=agent&user_id=user-1&created_after={cutoff}&limit=10"
        )

        assert resp.status_code == 200
        body = resp.json()
        # total reflects the filtered universe, not the raw session length.
        assert resp.headers["x-total-count"] == "3"
        assert len(body) == 3

    def test_limit_ge_1_validated(self, db_with_many_runs):
        """limit must be >= 1 (FastAPI validation -> 422)."""
        db, session = db_with_many_runs
        client = _build_client(db)

        resp = client.get(f"/sessions/{session.session_id}/runs?type=agent&user_id=user-1&limit=0")

        assert resp.status_code == 422
